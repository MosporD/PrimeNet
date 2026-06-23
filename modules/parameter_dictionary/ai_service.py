"""AI assistant for parameter dictionary Q&A."""

from __future__ import annotations

import os
from typing import Any

from .knowledge import _merge_vendor_sources, build_context, search_huawei, search_nokia

SYSTEM_PROMPT = """You are the PrimeNet Parameter Dictionary assistant for Nokia and Huawei RAN configuration.
Answer questions about what parameters do and which parameters relate to a feature or MO class.

Rules:
- Use ONLY the reference excerpts provided below. Do not invent parameter names or meanings.
- If the excerpts are insufficient, say what is missing and suggest more specific search terms.
- Be concise and practical for radio access network engineers.
- When listing related parameters, include MO class names where known.
- Cite specific parameter IDs/names from the excerpts.
"""


def _format_retrieval_answer(question: str, sources: list[dict[str, Any]]) -> str:
    """Format a readable answer directly from retrieved sources (no LLM)."""
    if not sources:
        return (
            "I could not find matching parameters or MOs in the dictionary for that question. "
            "Try a parameter ID, MO class name, or a shorter feature keyword (e.g. ANR, DRX, handover)."
        )

    lines = [f"Here is what I found for: **{question}**\n"]
    nokia = [s for s in sources if s.get("vendor") == "nokia"]
    huawei = [s for s in sources if s.get("vendor") == "huawei"]

    if nokia:
        lines.append("### Nokia")
        for src in nokia[:6]:
            if src.get("type") == "mo":
                lines.append(f"- **{src.get('mo')}** ({src.get('category')}): {src.get('description')}")
                params = src.get("parameters") or []
                for p in params[:5]:
                    lines.append(f"  - `{p.get('name')}`: {p.get('description')}")
                extra = int(src.get("parameter_count") or 0) - len(params)
                if extra > 0:
                    lines.append(f"  - … plus {extra} more parameters on this MO")
            else:
                mos = ", ".join(src.get("mo_list") or []) or "unknown MO"
                lines.append(f"- **`{src.get('parameter')}`** (MOs: {mos}): {src.get('description')}")

    if huawei:
        lines.append("\n### Huawei")
        for src in huawei[:5]:
            title = src.get("parameter_name") or src.get("name")
            meaning = src.get("meaning") or "See reference page for details."
            mo = src.get("mo") or ""
            pid = src.get("parameter_id") or ""
            header = title
            if pid:
                header = f"{title} (`{pid}`)"
            if mo:
                header += f" — MO {mo}"
            lines.append(f"- **{header}**: {meaning}")

    lines.append(
        "\n_Set `OPENAI_API_KEY` in the environment for natural-language summaries._"
    )
    return "\n".join(lines)


def _llm_answer(question: str, context: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    model = (os.getenv("AI_MODEL") or "gpt-4o-mini").strip()

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=900,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Reference excerpts from the parameter dictionary:\n\n{context}"
                ),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


def answer_question(question: str, vendor: str = "all") -> dict[str, Any]:
    """Answer a parameter dictionary question using retrieval + optional LLM."""
    question = (question or "").strip()
    vendor = (vendor or "all").lower()
    if vendor not in ("all", "nokia", "huawei"):
        vendor = "all"

    context, sources = build_context(question, vendor=vendor)

    if not sources:
        broad_nokia = search_nokia(question, limit=3) if vendor in ("all", "nokia") else []
        broad_huawei = search_huawei(question, limit=3) if vendor in ("all", "huawei") else []
        sources = broad_nokia + broad_huawei
        if sources:
            context, sources = build_context(question, vendor=vendor)

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if api_key and context:
        try:
            answer = _llm_answer(question, context)
            mode = "llm"
        except Exception as exc:
            answer = _format_retrieval_answer(question, sources)
            answer += f"\n\n_(AI summary unavailable: {exc})_"
            mode = "retrieval"
    else:
        answer = _format_retrieval_answer(question, sources)
        mode = "retrieval"

    return {
        "answer": answer,
        "sources": _public_sources(sources),
        "mode": mode,
        "vendor": vendor,
    }


def _public_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nokia = [src for src in sources if src.get("vendor") == "nokia"]
    huawei = [src for src in sources if src.get("vendor") == "huawei"]
    if nokia and huawei:
        ordered = _merge_vendor_sources(nokia, huawei, nokia_limit=6, huawei_limit=6)
    else:
        ordered = sources

    public: list[dict[str, Any]] = []
    for src in ordered[:12]:
        item: dict[str, Any] = {"vendor": src.get("vendor")}
        if src.get("vendor") == "nokia":
            if src.get("type") == "mo":
                item.update({
                    "type": "mo",
                    "label": src.get("mo"),
                    "description": src.get("description"),
                })
            else:
                item.update({
                    "type": "parameter",
                    "label": src.get("parameter"),
                    "description": src.get("description"),
                    "mo_list": src.get("mo_list") or [],
                })
        else:
            item.update({
                "type": "reference",
                "label": src.get("parameter_name") or src.get("name"),
                "url": src.get("url"),
                "description": src.get("meaning") or "",
            })
        public.append(item)
    return public
