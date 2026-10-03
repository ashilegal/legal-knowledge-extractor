"""Legal terms of art. They must keep their exact wording, so they never count as copying."""

from __future__ import annotations

import regex as re

LEGAL_TERMS = """
res judicata | collateral estoppel | claim preclusion | issue preclusion | direct estoppel
equitable estoppel | promissory estoppel | judicial estoppel | stare decisis | ratio decidendi
obiter dictum | obiter dicta | final judgment on the merits | judgment on the merits
final judgment | final order | summary judgment | default judgment | consent decree
declaratory judgment | preliminary injunction | permanent injunction | temporary restraining order
privity | in privity with | same cause of action | cause of action | primary right
burden of proof | standard of proof | preponderance of the evidence | clear and convincing evidence
beyond a reasonable doubt | prima facie case | prima facie | de novo | abuse of discretion
substantial evidence | judicial review | writ of mandate | writ of mandamus | writ of certiorari
quasi-judicial | administrative law judge | administrative proceeding | administrative remedies
exhaustion of administrative remedies | full faith and credit | statute of limitations
limitation period | laches | waiver | estoppel | mitigation of damages | punitive damages
compensatory damages | liquidated damages | specific performance | breach of contract
breach of duty | duty of care | standard of care | proximate cause | vicarious liability
respondeat superior | course of employment | scope of employment | wrongful termination
wrongful dismissal | constructive discharge | constructive dismissal | at-will employment
retrenchment | lay-off | layoff | lock-out | unfair labour practice | unfair labor practice
industrial dispute | collective bargaining agreement | collective bargaining | grievance procedure
arbitration award | arbitration agreement | binding arbitration | class action | class certification
due process | equal protection | natural justice | audi alteram partem | bona fide | mala fide
ultra vires | locus standi | sub judice | ex parte | inter alia | mens rea | actus reus
bodily injury | property damage | personal injury | occurrence | wrongful act | duty to defend
duty to indemnify | coverage | exclusion | insured | insurer | policyholder | indemnity
reasonable accommodation | disparate treatment | disparate impact | hostile work environment
protected activity | adverse employment action | retaliation | discrimination | harassment
""".replace("\n", " ")

_TERMS = sorted({t.strip().lower() for t in LEGAL_TERMS.split("|") if t.strip()},
                key=len, reverse=True)


def term_pattern(extra: list[str] | None = None) -> re.Pattern:
    """Regex matching the built-in legal terms plus extra exact terms (longest first)."""
    terms = set(_TERMS) | {" ".join(t.lower().split()) for t in (extra or []) if len(t) >= 3}
    alternatives = "|".join(re.escape(t).replace(r"\ ", r"\s+")
                            for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![\p{{L}}\p{{N}}])(?:{alternatives})(?![\p{{L}}\p{{N}}])",
                      re.IGNORECASE)


DEFAULT_PATTERN = term_pattern()
