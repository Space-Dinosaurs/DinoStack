"""Tests for schema validators."""
import pytest

from evals.icl_vs_orchestration.schema import (
    validate_ae_spec,
    validate_corpus_manifest,
    validate_icl_spec,
    validate_ticket,
)


def test_validate_manifest_valid():
    validate_corpus_manifest({
        "corpus_name": "smoke",
        "ticket_classes": ["trivial"],
        "tickets": ["t1"],
    })  # should not raise


def test_validate_manifest_missing_tickets():
    with pytest.raises(ValueError, match="tickets"):
        validate_corpus_manifest({"corpus_name": "smoke", "ticket_classes": []})


def test_validate_manifest_tickets_not_list():
    with pytest.raises(ValueError, match="list"):
        validate_corpus_manifest({
            "corpus_name": "smoke",
            "ticket_classes": [],
            "tickets": "t1",
        })


def test_validate_ticket_valid():
    validate_ticket({
        "ticket_id": "t1",
        "ticket_class": "trivial",
        "description": "test",
    }, "t1")  # should not raise


def test_validate_ticket_missing_description():
    with pytest.raises(ValueError, match="description"):
        validate_ticket({"ticket_id": "t1", "ticket_class": "trivial"}, "t1")


def test_validate_ticket_invalid_class():
    with pytest.raises(ValueError, match="ticket_class"):
        validate_ticket({
            "ticket_id": "t1",
            "ticket_class": "not-a-real-class",
            "description": "test",
        }, "t1")


def test_validate_ae_spec_valid():
    validate_ae_spec({
        "spec_version": "v1",
        "content_sha": "abc123",
        "execution_mode": "single-shot",
    })  # should not raise


def test_validate_ae_spec_invalid_mode():
    with pytest.raises(ValueError, match="execution_mode"):
        validate_ae_spec({
            "spec_version": "v1",
            "content_sha": "abc123",
            "execution_mode": "unknown-mode",
        })


def test_validate_ae_spec_multiturn_requires_max_turns():
    with pytest.raises(ValueError, match="max_turns"):
        validate_ae_spec({
            "spec_version": "v1",
            "content_sha": "abc123",
            "execution_mode": "sdk-multiturn",
            # Missing max_turns
        })


def test_validate_icl_spec_valid():
    validate_icl_spec({
        "spec_version": "v1",
        "file_selection_rule": "all",
        "context_budget_tokens": 200000,
        "prompt_template_path": "stub",
        "model": "claude-sonnet",
        "max_turns": 1,
        "allowed_tools": ["Read"],
    })  # should not raise


def test_validate_icl_spec_missing_fields():
    with pytest.raises(ValueError, match="model"):
        validate_icl_spec({
            "spec_version": "v1",
            "file_selection_rule": "all",
            "context_budget_tokens": 200000,
            # missing prompt_template_path, model, max_turns, allowed_tools
        })


def test_validate_icl_spec_budget_not_int():
    with pytest.raises(ValueError, match="integer"):
        validate_icl_spec({
            "spec_version": "v1",
            "file_selection_rule": "all",
            "context_budget_tokens": "200k",
            "prompt_template_path": "stub",
            "model": "claude-sonnet",
            "max_turns": 1,
            "allowed_tools": ["Read"],
        })
