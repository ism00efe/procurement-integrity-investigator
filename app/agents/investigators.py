import asyncio
import json
import logging

from pydantic import ValidationError

from app.agents.providers.base import LLMProvider, LLMProviderError
from app.agents.schemas import InvestigatorOutput
from app.agents.tools import TOOL_SPECS, dispatch_tool

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 5

SHARED_RULES = """You are one of three specialist analysts investigating a public procurement
case that a deterministic risk-scoring engine flagged for human review. You are NOT a judge,
auditor with subpoena power, or law-enforcement officer, and you must never accuse anyone of
corruption, fraud, or bribery. Your job is strictly to surface risk indicators, unusual
patterns, and open questions that a human investigator should look into next.

Hard rules:
- Never write that a case "is corrupt", "is fraudulent", or that wrongdoing "occurred" or is
  "confirmed". Use language like "risk indicator", "unusual pattern", "requires review",
  "possible anomaly", or "insufficient evidence".
- Every claim must be traceable: only cite evidence_refs that were returned to you by a tool
  call in this conversation. Do not invent record IDs.
- Actively consider and state benign, legitimate explanations for each pattern you find
  (e.g. specialized/emergency procurement, small supplier market, legitimate repeat vendor
  relationships).
- Use the provided tools to gather facts before writing findings — do not guess numbers.
  Call at least one tool relevant to your role before producing your final answer.
- Stay in your lane. Two other specialists are covering procedure, supplier history, and
  price separately. Do not file a standalone finding that just restates a fact belonging to
  another specialty (e.g. bidder count, procurement method, tender-period length) unless you
  are directly connecting it to your own specialty's evidence to explain a specific
  conclusion (e.g. "peer comparison confidence is low because only one bidder means less
  price discovery happened"). If your area of focus has nothing further to add for this
  case, return fewer findings rather than padding with another specialty's facts.
- Never state that a value "may be high" or "may be low" (or similarly vague/hedged
  comparative language) without citing a specific number from a tool result to support it.
  If a tool reports that comparison data is insufficient, say exactly that as your finding
  (e.g. "insufficient comparable data to assess whether this value is unusual") instead of
  speculating.
- When you are done gathering evidence, respond with ONLY a single JSON object (no prose,
  no markdown fences) matching exactly this shape:
  {"investigator": "<your role id>", "case_id": "<case id>", "summary": "<1-3 sentences>",
   "findings": [{"claim": "...", "evidence_refs": ["..."], "confidence": 0.0-1.0,
   "risk_level": "low|medium|high", "benign_explanation": "..."}]}
"""

INVESTIGATOR_SPECS = [
    {
        "id": "procedure",
        "role": "Procurement / Procedure Analyst",
        "focus": (
            "Determine what happened procedurally: the procurement method used, bidding "
            "characteristics (e.g. number of tenderers), timing (tender period length vs. "
            "typical practice), and any procedural risk indicators. Use get_tender_details "
            "and get_competing_bidders."
        ),
    },
    {
        "id": "supplier",
        "role": "Supplier / Relationship Analyst",
        "focus": (
            "Determine the winning supplier's history: how concentrated its awards are, "
            "whether it repeatedly wins from the same buyer, and whether that pattern is "
            "unusual relative to the buyer's overall supplier base. Use get_supplier_history, "
            "get_buyer_history, and get_related_contracts. Bidder count, procurement method, "
            "and tender-period length are the Procedure analyst's territory, not yours — do "
            "not file a finding about them."
        ),
    },
    {
        "id": "price",
        "role": "Price / Benchmark Analyst",
        "focus": (
            "Determine whether the tender's estimated or awarded value looks unusual compared "
            "to similar tenders, and whether the awarded value deviates materially from the "
            "tender's own estimate. Use get_peer_price_comparison and get_tender_details, and "
            "consider legitimate reasons values can differ (scope, urgency, specification). "
            "Bidder count, procurement method, and tender-period length are the Procedure "
            "analyst's territory, not yours — do not file a finding about them, even briefly."
        ),
    },
]


async def _run_tool_loop(provider: LLMProvider, messages: list[dict]) -> str:
    for _ in range(MAX_TOOL_TURNS):
        message = await provider.chat(messages, tools=TOOL_SPECS)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return message.get("content") or ""

        messages.append(message)
        for call in tool_calls:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = dispatch_tool(fn.get("name", ""), args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": json.dumps(result, default=str),
            })
    # Ran out of turns: force a final answer with no more tools offered.
    final = await provider.chat(messages, tools=None)
    return final.get("content") or ""


def _parse_output(raw: str, investigator_id: str, case_id: str) -> InvestigatorOutput:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text)
    # The model is inconsistent about what it puts in "investigator"/"case_id"
    # (sometimes the descriptive role name, sometimes a slug, occasionally a
    # typo'd case id) -- these are already known from context, so don't trust
    # the model's self-report for fields we can set authoritatively.
    data["investigator"] = investigator_id
    data["case_id"] = case_id
    return InvestigatorOutput.model_validate(data)


async def run_investigator(
    provider: LLMProvider, semaphore: asyncio.Semaphore, spec: dict, case_seed: dict,
) -> InvestigatorOutput:
    case_id = case_seed["case_id"]
    system = SHARED_RULES + f"\nYour specific role: {spec['role']}.\n{spec['focus']}"
    user = (
        f"Investigate case {case_id}.\n\nDeterministic risk-engine context (a starting point, "
        "not proof of anything):\n" + json.dumps(case_seed, indent=2, default=str)
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async with semaphore:
        try:
            raw = await _run_tool_loop(provider, messages)
        except LLMProviderError as exc:
            logger.warning("Investigator %s failed for %s: %s", spec["id"], case_id, exc)
            return InvestigatorOutput(
                investigator=spec["role"], case_id=case_id,
                summary=f"Investigation call failed: {exc}", findings=[],
            )

    try:
        return _parse_output(raw, spec["role"], case_id)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Repairing malformed output from %s for %s: %s", spec["id"], case_id, exc)

    # One repair attempt: ask the model to re-emit strict JSON only.
    messages.append({"role": "assistant", "content": raw})
    messages.append({
        "role": "user",
        "content": (
            "That was not valid JSON matching the required schema. Respond again with ONLY "
            "the JSON object, no prose, no markdown fences."
        ),
    })
    try:
        async with semaphore:
            repaired = await provider.chat(messages, tools=None)
        return _parse_output(repaired.get("content") or "", spec["role"], case_id)
    except (LLMProviderError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Repair failed for %s on %s: %s", spec["id"], case_id, exc)
        return InvestigatorOutput(
            investigator=spec["role"], case_id=case_id,
            summary="Investigator output could not be parsed as valid structured JSON after retry.",
            findings=[],
        )


async def investigate_case(provider: LLMProvider, semaphore: asyncio.Semaphore, case_seed: dict) -> list[InvestigatorOutput]:
    tasks = [run_investigator(provider, semaphore, spec, case_seed) for spec in INVESTIGATOR_SPECS]
    return await asyncio.gather(*tasks)
