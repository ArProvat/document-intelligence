import difflib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.models.api_schemas import (
    AppliedStyleRule,
    DraftFeedbackResponse,
    DraftType,
    EvidenceItem,
    StructuredDiffEntry,
    StyleRule,
    StyleRuleCategory,
)


class DraftRunRecord(BaseModel):
    draft_id: str
    user_id: str
    session_id: str
    draft_type: DraftType
    instructions: str | None = None
    retrieval_query: str
    draft: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    applied_rule_ids: List[str] = Field(default_factory=list)
    generated_at: datetime


class FeedbackEventRecord(BaseModel):
    feedback_id: str
    draft_id: str
    user_id: str
    draft_type: DraftType
    original_draft: str
    edited_draft: str
    operator_notes: str | None = None
    retrieval_query: str
    structured_diff: List[StructuredDiffEntry] = Field(default_factory=list)
    extracted_rule_ids: List[str] = Field(default_factory=list)
    created_at: datetime


class StyleRuleRecord(BaseModel):
    rule_id: str
    user_id: str
    description: str
    category: StyleRuleCategory
    example_before: str
    example_after: str
    applicable_draft_types: List[DraftType] = Field(default_factory=list)
    confidence: float
    support_count: int = 1
    decay_count: int = 0
    normalized_key: str
    last_updated: datetime


class ExtractedRuleCandidate(BaseModel):
    description: str
    category: StyleRuleCategory
    example_before: str
    example_after: str
    applicable_draft_types: List[DraftType] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class RuleExtractionEnvelope(BaseModel):
    rules: List[ExtractedRuleCandidate] = Field(default_factory=list)


class DraftImprovementStore:
    def __init__(self, persist_directory: str = "./draft_learning_store"):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._draft_runs_path = self.persist_directory / "draft_runs.json"
        self._feedback_path = self.persist_directory / "feedback_events.json"
        self._rules_path = self.persist_directory / "style_rules.json"
        self._draft_runs: Dict[str, DraftRunRecord] = self._load_records(
            self._draft_runs_path,
            DraftRunRecord,
            "draft_id",
        )
        self._feedback_events: Dict[str, FeedbackEventRecord] = self._load_records(
            self._feedback_path,
            FeedbackEventRecord,
            "feedback_id",
        )
        self._rules: Dict[str, StyleRuleRecord] = self._load_records(
            self._rules_path,
            StyleRuleRecord,
            "rule_id",
        )

    def _load_records(self, path: Path, model_cls, key_field: str):
        if not path.exists():
            return {}

        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            item[key_field]: model_cls.model_validate(item)
            for item in data
        }

    def _save_records(self, path: Path, records: Dict[str, BaseModel]) -> None:
        path.write_text(
            json.dumps(
                [record.model_dump(mode="json") for record in records.values()],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def save_draft_run(self, record: DraftRunRecord) -> None:
        self._draft_runs[record.draft_id] = record
        self._save_records(self._draft_runs_path, self._draft_runs)

    def get_draft_run(self, draft_id: str) -> DraftRunRecord | None:
        return self._draft_runs.get(draft_id)

    def save_feedback_event(self, record: FeedbackEventRecord) -> None:
        self._feedback_events[record.feedback_id] = record
        self._save_records(self._feedback_path, self._feedback_events)

    def save_rule(self, record: StyleRuleRecord) -> None:
        self._rules[record.rule_id] = record
        self._save_records(self._rules_path, self._rules)

    def delete_rule(self, rule_id: str) -> None:
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._save_records(self._rules_path, self._rules)

    def get_rule(self, rule_id: str) -> StyleRuleRecord | None:
        return self._rules.get(rule_id)

    def list_rules_for_user(self, user_id: str) -> List[StyleRuleRecord]:
        return [rule for rule in self._rules.values() if rule.user_id == user_id]


class DraftImprovementService:
    def __init__(self, store: DraftImprovementStore):
        self.store = store
        self.rule_extractor = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            RuleExtractionEnvelope
        )
        self.rule_prompt = ChatPromptTemplate.from_template(
            """
You are analyzing how a senior legal operator edited a junior draft.

Your task:
- infer reusable writing preferences from the edit
- extract general rules that should apply to future drafts
- focus on style, structure, completeness, citation practice, formatting, and analytical expectations
- do not extract case-specific factual corrections unless they clearly imply a reusable drafting rule
- do not restate the same rule multiple times

Return only rules that are generalizable.

Draft type:
{draft_type}

Retrieval query:
{retrieval_query}

Operator notes:
{operator_notes}

Original draft:
{original_draft}

Edited draft:
{edited_draft}

Structured diff:
{structured_diff}
"""
        )

    def _normalize_rule_key(self, description: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", description.lower()).strip()

    def _build_structured_diff(self, before: str, after: str) -> List[StructuredDiffEntry]:
        before_blocks = [block.strip() for block in before.split("\n\n") if block.strip()]
        after_blocks = [block.strip() for block in after.split("\n\n") if block.strip()]
        diff_entries: List[StructuredDiffEntry] = []

        matcher = difflib.SequenceMatcher(a=before_blocks, b=after_blocks)
        for operation, i1, i2, j1, j2 in matcher.get_opcodes():
            if operation == "equal":
                continue

            diff_entries.append(
                StructuredDiffEntry(
                    operation=operation,
                    before="\n\n".join(before_blocks[i1:i2]),
                    after="\n\n".join(after_blocks[j1:j2]),
                )
            )

        return diff_entries

    def _to_public_rule(self, record: StyleRuleRecord) -> StyleRule:
        return StyleRule(
            rule_id=record.rule_id,
            description=record.description,
            category=record.category,
            example_before=record.example_before,
            example_after=record.example_after,
            applicable_draft_types=record.applicable_draft_types,
            confidence=record.confidence,
            support_count=record.support_count,
            last_updated=record.last_updated,
        )

    def _extract_rule_candidates(
        self,
        draft_type: DraftType,
        retrieval_query: str,
        original_draft: str,
        edited_draft: str,
        operator_notes: str | None,
        structured_diff: List[StructuredDiffEntry],
    ) -> List[ExtractedRuleCandidate]:
        response = self.rule_prompt | self.rule_extractor
        envelope = response.invoke(
            {
                "draft_type": draft_type.value,
                "retrieval_query": retrieval_query,
                "operator_notes": operator_notes or "None",
                "original_draft": original_draft,
                "edited_draft": edited_draft,
                "structured_diff": json.dumps(
                    [entry.model_dump() for entry in structured_diff],
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )
        return envelope.rules

    def _merge_extracted_rules(
        self,
        user_id: str,
        draft_type: DraftType,
        extracted_rules: List[ExtractedRuleCandidate],
    ) -> List[StyleRuleRecord]:
        existing_rules = self.store.list_rules_for_user(user_id)
        existing_by_key = {rule.normalized_key: rule for rule in existing_rules}
        now = datetime.now(timezone.utc)
        merged_records: List[StyleRuleRecord] = []

        for candidate in extracted_rules:
            normalized_key = self._normalize_rule_key(candidate.description)
            if not normalized_key:
                continue

            applicable_draft_types = candidate.applicable_draft_types or [draft_type]
            existing = existing_by_key.get(normalized_key)

            if existing:
                existing.description = candidate.description
                existing.category = candidate.category
                existing.example_before = candidate.example_before or existing.example_before
                existing.example_after = candidate.example_after or existing.example_after
                existing.applicable_draft_types = list(
                    {
                        *existing.applicable_draft_types,
                        *applicable_draft_types,
                    }
                )
                existing.confidence = min(1.0, max(existing.confidence, candidate.confidence) + 0.1)
                existing.support_count += 1
                existing.last_updated = now
                self.store.save_rule(existing)
                merged_records.append(existing)
                continue

            new_rule = StyleRuleRecord(
                rule_id=str(uuid.uuid4()),
                user_id=user_id,
                description=candidate.description,
                category=candidate.category,
                example_before=candidate.example_before,
                example_after=candidate.example_after,
                applicable_draft_types=applicable_draft_types,
                confidence=candidate.confidence,
                support_count=1,
                decay_count=0,
                normalized_key=normalized_key,
                last_updated=now,
            )
            self.store.save_rule(new_rule)
            existing_by_key[normalized_key] = new_rule
            merged_records.append(new_rule)

        return merged_records

    def _apply_feedback_decay(
        self,
        draft_run: DraftRunRecord,
        reinforced_rule_ids: List[str],
    ) -> None:
        reinforced = set(reinforced_rule_ids)

        for rule_id in draft_run.applied_rule_ids:
            rule = self.store.get_rule(rule_id)
            if not rule or rule.user_id != draft_run.user_id:
                continue

            if rule_id in reinforced:
                rule.confidence = min(1.0, rule.confidence + 0.1)
                rule.support_count += 1
                rule.decay_count = max(0, rule.decay_count - 1)
            else:
                rule.confidence = max(0.0, rule.confidence - 0.05)
                rule.decay_count += 1

            rule.last_updated = datetime.now(timezone.utc)

            if rule.confidence < 0.2 and rule.decay_count >= 2:
                self.store.delete_rule(rule.rule_id)
            else:
                self.store.save_rule(rule)

    def active_rules_for_user(
        self,
        user_id: str,
        draft_type: DraftType,
        min_confidence: float = 0.5,
    ) -> List[StyleRule]:
        rules = [
            rule
            for rule in self.store.list_rules_for_user(user_id)
            if rule.confidence >= min_confidence
            and (not rule.applicable_draft_types or draft_type in rule.applicable_draft_types)
        ]
        rules.sort(key=lambda rule: (-rule.confidence, -rule.support_count, rule.description))
        return [self._to_public_rule(rule) for rule in rules]

    def format_rules_for_prompt(self, user_id: str, draft_type: DraftType) -> tuple[str, List[AppliedStyleRule]]:
        rules = self.active_rules_for_user(user_id, draft_type)
        if not rules:
            return "None", []

        lines = []
        applied_rules: List[AppliedStyleRule] = []
        for index, rule in enumerate(rules, start=1):
            lines.append(f"{index}. [{rule.category.value}] {rule.description}")
            applied_rules.append(
                AppliedStyleRule(
                    rule_id=rule.rule_id,
                    description=rule.description,
                    category=rule.category,
                    confidence=rule.confidence,
                )
            )

        return "\n".join(lines), applied_rules

    def register_generated_draft(
        self,
        user_id: str,
        session_id: str,
        draft_type: DraftType,
        instructions: str | None,
        retrieval_query: str,
        draft: str,
        evidence: List[EvidenceItem],
        applied_rules: List[AppliedStyleRule],
    ) -> str:
        draft_id = str(uuid.uuid4())
        self.store.save_draft_run(
            DraftRunRecord(
                draft_id=draft_id,
                user_id=user_id,
                session_id=session_id,
                draft_type=draft_type,
                instructions=instructions,
                retrieval_query=retrieval_query,
                draft=draft,
                evidence=evidence,
                applied_rule_ids=[rule.rule_id for rule in applied_rules],
                generated_at=datetime.now(timezone.utc),
            )
        )
        return draft_id

    def capture_feedback(
        self,
        draft_id: str,
        edited_draft: str,
        operator_notes: str | None = None,
    ) -> DraftFeedbackResponse:
        draft_run = self.store.get_draft_run(draft_id)
        if not draft_run:
            raise ValueError("Draft not found")

        structured_diff = self._build_structured_diff(draft_run.draft, edited_draft)
        extracted_candidates = self._extract_rule_candidates(
            draft_type=draft_run.draft_type,
            retrieval_query=draft_run.retrieval_query,
            original_draft=draft_run.draft,
            edited_draft=edited_draft,
            operator_notes=operator_notes,
            structured_diff=structured_diff,
        )
        merged_rules = self._merge_extracted_rules(
            user_id=draft_run.user_id,
            draft_type=draft_run.draft_type,
            extracted_rules=extracted_candidates,
        )
        self._apply_feedback_decay(
            draft_run=draft_run,
            reinforced_rule_ids=[rule.rule_id for rule in merged_rules],
        )

        feedback_id = str(uuid.uuid4())
        self.store.save_feedback_event(
            FeedbackEventRecord(
                feedback_id=feedback_id,
                draft_id=draft_run.draft_id,
                user_id=draft_run.user_id,
                draft_type=draft_run.draft_type,
                original_draft=draft_run.draft,
                edited_draft=edited_draft,
                operator_notes=operator_notes,
                retrieval_query=draft_run.retrieval_query,
                structured_diff=structured_diff,
                extracted_rule_ids=[rule.rule_id for rule in merged_rules],
                created_at=datetime.now(timezone.utc),
            )
        )

        return DraftFeedbackResponse(
            feedback_id=feedback_id,
            draft_id=draft_run.draft_id,
            extracted_rules=[self._to_public_rule(rule) for rule in merged_rules],
            active_rules=self.active_rules_for_user(draft_run.user_id, draft_run.draft_type),
            structured_diff=structured_diff,
        )
