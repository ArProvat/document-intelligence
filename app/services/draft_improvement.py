import difflib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.models.api_schemas import (
    AppliedStyleRule,
    DraftFeedbackResponse,
    DraftType,
    EvidenceItem,
    FeedbackJobStatus,
    StructuredDiffEntry,
    StyleRule,
    StyleRuleCategory,
    StyleRuleStatus,
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
    status: FeedbackJobStatus = FeedbackJobStatus.PENDING
    structured_diff: List[StructuredDiffEntry] = Field(default_factory=list)
    extracted_rule_ids: List[str] = Field(default_factory=list)
    error_message: str | None = None
    submitted_at: datetime
    processed_at: datetime | None = None


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
    status: StyleRuleStatus = StyleRuleStatus.ACTIVE
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
        self._lock = threading.RLock()
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
        return {item[key_field]: model_cls.model_validate(item) for item in data}

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
        with self._lock:
            self._draft_runs[record.draft_id] = record
            self._save_records(self._draft_runs_path, self._draft_runs)

    def get_draft_run(self, draft_id: str) -> DraftRunRecord | None:
        with self._lock:
            return self._draft_runs.get(draft_id)

    def save_feedback_event(self, record: FeedbackEventRecord) -> None:
        with self._lock:
            self._feedback_events[record.feedback_id] = record
            self._save_records(self._feedback_path, self._feedback_events)

    def get_feedback_event(self, feedback_id: str) -> FeedbackEventRecord | None:
        with self._lock:
            return self._feedback_events.get(feedback_id)

    def save_rule(self, record: StyleRuleRecord) -> None:
        with self._lock:
            self._rules[record.rule_id] = record
            self._save_records(self._rules_path, self._rules)

    def delete_rule(self, rule_id: str) -> None:
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                self._save_records(self._rules_path, self._rules)

    def get_rule(self, rule_id: str) -> StyleRuleRecord | None:
        with self._lock:
            return self._rules.get(rule_id)

    def list_rules_for_user(self, user_id: str) -> List[StyleRuleRecord]:
        with self._lock:
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

    def _similarity_score(self, left: str, right: str) -> float:
        return difflib.SequenceMatcher(a=left, b=right).ratio()

    def _token_overlap(self, left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

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
            status=record.status,
            last_updated=record.last_updated,
        )

    def _feedback_response(self, feedback_event: FeedbackEventRecord) -> DraftFeedbackResponse:
        extracted_rules = []
        for rule_id in feedback_event.extracted_rule_ids:
            rule = self.store.get_rule(rule_id)
            if rule:
                extracted_rules.append(self._to_public_rule(rule))

        active_rules = self.active_rules_for_user(
            feedback_event.user_id,
            feedback_event.draft_type,
        )

        return DraftFeedbackResponse(
            feedback_id=feedback_event.feedback_id,
            draft_id=feedback_event.draft_id,
            status=feedback_event.status,
            extracted_rules=extracted_rules,
            active_rules=active_rules,
            structured_diff=feedback_event.structured_diff,
            error_message=feedback_event.error_message,
            submitted_at=feedback_event.submitted_at,
            processed_at=feedback_event.processed_at,
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

    def _find_best_matching_rule(
        self,
        existing_rules: List[StyleRuleRecord],
        candidate: ExtractedRuleCandidate,
        normalized_key: str,
    ) -> StyleRuleRecord | None:
        best_rule = None
        best_score = 0.0

        for rule in existing_rules:
            if rule.category != candidate.category:
                continue

            similarity = self._similarity_score(rule.normalized_key, normalized_key)
            overlap = self._token_overlap(rule.normalized_key, normalized_key)

            if rule.normalized_key == normalized_key:
                return rule

            if normalized_key in rule.normalized_key or rule.normalized_key in normalized_key:
                score = max(similarity, overlap, 0.92)
            else:
                score = max(similarity, overlap)

            if score > best_score and (score >= 0.86 or overlap >= 0.6):
                best_rule = rule
                best_score = score

        return best_rule

    def _merge_extracted_rules(
        self,
        user_id: str,
        draft_type: DraftType,
        extracted_rules: List[ExtractedRuleCandidate],
    ) -> List[StyleRuleRecord]:
        existing_rules = self.store.list_rules_for_user(user_id)
        now = datetime.now(timezone.utc)
        merged_records: List[StyleRuleRecord] = []

        for candidate in extracted_rules:
            normalized_key = self._normalize_rule_key(candidate.description)
            if not normalized_key:
                continue

            applicable_draft_types = candidate.applicable_draft_types or [draft_type]
            existing = self._find_best_matching_rule(existing_rules, candidate, normalized_key)

            if existing:
                existing.description = candidate.description
                existing.example_before = candidate.example_before or existing.example_before
                existing.example_after = candidate.example_after or existing.example_after
                existing.applicable_draft_types = sorted(
                    {
                        *existing.applicable_draft_types,
                        *applicable_draft_types,
                    },
                    key=lambda item: item.value,
                )
                existing.normalized_key = normalized_key
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
                status=StyleRuleStatus.ACTIVE,
                last_updated=now,
            )
            self.store.save_rule(new_rule)
            existing_rules.append(new_rule)
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
            if not rule or rule.user_id != draft_run.user_id or rule.status != StyleRuleStatus.ACTIVE:
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
            if rule.status == StyleRuleStatus.ACTIVE
            and rule.confidence >= min_confidence
            and (not rule.applicable_draft_types or draft_type in rule.applicable_draft_types)
        ]
        rules.sort(key=lambda rule: (-rule.confidence, -rule.support_count, rule.description))
        return [self._to_public_rule(rule) for rule in rules]

    def list_rules_for_user(
        self,
        user_id: str,
        draft_type: DraftType | None = None,
        include_disabled: bool = True,
    ) -> List[StyleRule]:
        rules = []
        for rule in self.store.list_rules_for_user(user_id):
            if not include_disabled and rule.status != StyleRuleStatus.ACTIVE:
                continue
            if draft_type is not None and rule.applicable_draft_types and draft_type not in rule.applicable_draft_types:
                continue
            rules.append(rule)

        rules.sort(key=lambda rule: (rule.status != StyleRuleStatus.ACTIVE, -rule.confidence, -rule.support_count))
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

    def submit_feedback_job(
        self,
        draft_id: str,
        edited_draft: str,
        operator_notes: str | None = None,
    ) -> DraftFeedbackResponse:
        draft_run = self.store.get_draft_run(draft_id)
        if not draft_run:
            raise ValueError("Draft not found")

        feedback_event = FeedbackEventRecord(
            feedback_id=str(uuid.uuid4()),
            draft_id=draft_run.draft_id,
            user_id=draft_run.user_id,
            draft_type=draft_run.draft_type,
            original_draft=draft_run.draft,
            edited_draft=edited_draft,
            operator_notes=operator_notes,
            retrieval_query=draft_run.retrieval_query,
            status=FeedbackJobStatus.PENDING,
            submitted_at=datetime.now(timezone.utc),
        )
        self.store.save_feedback_event(feedback_event)
        return self._feedback_response(feedback_event)

    def process_feedback_job(self, feedback_id: str) -> None:
        feedback_event = self.store.get_feedback_event(feedback_id)
        if not feedback_event:
            return

        feedback_event.status = FeedbackJobStatus.PROCESSING
        feedback_event.error_message = None
        self.store.save_feedback_event(feedback_event)

        draft_run = self.store.get_draft_run(feedback_event.draft_id)
        if not draft_run:
            feedback_event.status = FeedbackJobStatus.FAILED
            feedback_event.error_message = "Draft not found"
            feedback_event.processed_at = datetime.now(timezone.utc)
            self.store.save_feedback_event(feedback_event)
            return

        try:
            structured_diff = self._build_structured_diff(draft_run.draft, feedback_event.edited_draft)
            extracted_candidates = self._extract_rule_candidates(
                draft_type=draft_run.draft_type,
                retrieval_query=draft_run.retrieval_query,
                original_draft=draft_run.draft,
                edited_draft=feedback_event.edited_draft,
                operator_notes=feedback_event.operator_notes,
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

            feedback_event.structured_diff = structured_diff
            feedback_event.extracted_rule_ids = [rule.rule_id for rule in merged_rules]
            feedback_event.status = FeedbackJobStatus.COMPLETED
            feedback_event.processed_at = datetime.now(timezone.utc)
            feedback_event.error_message = None
            self.store.save_feedback_event(feedback_event)
        except Exception as exc:
            feedback_event.status = FeedbackJobStatus.FAILED
            feedback_event.error_message = str(exc)
            feedback_event.processed_at = datetime.now(timezone.utc)
            self.store.save_feedback_event(feedback_event)

    def get_feedback_status(self, feedback_id: str) -> DraftFeedbackResponse:
        feedback_event = self.store.get_feedback_event(feedback_id)
        if not feedback_event:
            raise ValueError("Feedback job not found")
        return self._feedback_response(feedback_event)

    def disable_rule(self, user_id: str, rule_id: str) -> StyleRule:
        rule = self.store.get_rule(rule_id)
        if not rule or rule.user_id != user_id:
            raise ValueError("Style rule not found")

        rule.status = StyleRuleStatus.DISABLED
        rule.last_updated = datetime.now(timezone.utc)
        self.store.save_rule(rule)
        return self._to_public_rule(rule)

    def enable_rule(self, user_id: str, rule_id: str) -> StyleRule:
        rule = self.store.get_rule(rule_id)
        if not rule or rule.user_id != user_id:
            raise ValueError("Style rule not found")

        rule.status = StyleRuleStatus.ACTIVE
        rule.last_updated = datetime.now(timezone.utc)
        self.store.save_rule(rule)
        return self._to_public_rule(rule)

    def delete_rule_for_user(self, user_id: str, rule_id: str) -> None:
        rule = self.store.get_rule(rule_id)
        if not rule or rule.user_id != user_id:
            raise ValueError("Style rule not found")
        self.store.delete_rule(rule_id)
