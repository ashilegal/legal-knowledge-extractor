from lke.terms import find_terms, key, normalise, protected_terms, same


def kinds(text):
    return {(t.kind, t.text) for t in find_terms(text)}


def test_indian_identifiers():
    text = ("In Workmen of Meenakshi Mills Ltd. v. Meenakshi Mills Ltd., (1992) 3 SCC 336, "
            "the Supreme Court of India read Section 25F of the Industrial Disputes Act, 1947 "
            "with Article 21 of the Constitution of India.")
    found = kinds(text)
    assert ("case_name", "Workmen of Meenakshi Mills Ltd. v. Meenakshi Mills Ltd.") in found
    assert ("citation", "(1992) 3 SCC 336") in found
    assert ("court", "Supreme Court of India") in found
    assert ("provision", "Section 25F") in found
    assert ("provision", "Article 21") in found
    assert ("statute", "Industrial Disputes Act, 1947") in found


def test_us_and_uk_identifiers():
    text = ("See HS Services, Inc. v. Nationwide Mut. Ins. Co. (9th Cir. 1997) 109 F3d 642; "
            "Ins.C. § 533 bars coverage. Compare Donoghue v Stevenson [1932] UKHL 100 and "
            "42 U.S.C. § 1983. Decided on 21 March 1978 and on March 21, 1978.")
    found = kinds(text)
    assert ("case_name", "HS Services, Inc. v. Nationwide Mut. Ins. Co.") in found
    assert ("citation", "109 F3d 642") in found
    assert ("provision", "Ins.C. § 533") in found
    assert ("case_name", "Donoghue v Stevenson") in found
    assert ("citation", "[1932] UKHL 100") in found
    assert ("provision", "42 U.S.C. § 1983") in found
    assert ("date", "21 March 1978") in found
    assert ("date", "March 21, 1978") in found


def test_defined_terms():
    text = '“Personal injury”: injury other than bodily injury. "Workman" means any person.'
    found = kinds(text)
    assert ("defined_term", "Personal injury") in found
    assert ("defined_term", "Workman") in found


def test_normalisation_and_keys():
    assert normalise("provision", "S. 25-F") == "Section 25F"
    assert normalise("provision", "Sec 25F") == "Section 25F"
    assert normalise("provision", "Art. 21") == "Article 21"
    assert normalise("case_name", "Donoghue vs Stevenson") == "Donoghue v. Stevenson"
    assert same("case_name", "ABC Limited v. XYZ", "ABC Ltd. vs XYZ")
    assert same("provision", "s.25F", "Section 25-F")
    assert key("statute", "The Industrial Disputes Act, 1947") == key(
        "statute", "Industrial Disputes Act 1947")


def test_protected_terms_prompt_list():
    terms = protected_terms("Section 25F and S. 25-F of the Industrial Disputes Act, 1947.")
    assert terms.by_kind["provision"] == ["Section 25F"]          # one entry, two spellings
    assert terms.contains("provision", "section 25-F")
    assert "Industrial Disputes Act, 1947" in terms.as_prompt_list()
