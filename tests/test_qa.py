from server.pipeline import qa


def test_ok():
    assert qa.check("We trained on 8 GPUs [12].", "අපි GPUs 8කින් train කළා [12].") == []


def test_missing_number_and_citation():
    issues = qa.check("BLEU of 28.4 on WMT 2014 [9].", "BLEU එක හොඳයි.")
    assert "missing_numbers:28.4,2014" in issues and "missing_citations:[9]" in issues
    assert qa.wants_retry(issues) and not qa.is_hard(issues)


def test_no_sinhala_is_hard():
    issues = qa.check("This is a long English sentence that was not translated.", "This is a long English sentence.")
    assert qa.is_hard(issues)


def test_numbers_with_commas():
    assert qa.check("about 4,500 pairs", "pairs 4500ක් විතර") == []
