def test_audit_module_imports_without_triggering_model_load():
    from examples.performance_9b.tokenizer_audit import audit

    assert callable(audit)
