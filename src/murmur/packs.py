"""Word packs: curated dictionaries you switch on instead of typing out.

A pack is the same two mechanisms the personal dictionary uses (vocabulary
to snap spelling, replacements for exact heard-to-typed fixes), shipped with
Murmur and toggled from the settings page. The point is the first day: a
team that all says the same product names should not each discover
independently that "XM" comes out as "ex em".

Packs never touch `config.vocabulary` or `config.replacements`. They are
merged in at transcription time and the user's own entries go first, so a
personal fix always beats a pack's and nothing a pack ships can be silently
edited into someone's own dictionary (or exported as if it were theirs).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    description: str
    vocabulary: tuple[str, ...]
    # (heard, typed) pairs, matched case-insensitively on word boundaries.
    replacements: tuple[tuple[str, str], ...]


# Deliberately conservative on both lists. A vocabulary entry that is also an
# ordinary English word ("segment", "frontline", "lifecycle") would recase it
# mid-sentence, and a replacement whose left side can occur in real speech
# ("stand up") would rewrite the wrong thing, so neither kind is here.
QUALTRICS = Pack(
    id="qualtrics",
    name="Qualtrics",
    description="Product names, XM jargon, and the acronyms product managers say all day.",
    vocabulary=(
        # Qualtrics products. The "<common word>XM" names are deliberately NOT
        # here: vocabulary snapping is fuzzy, so "CrossXM" scores 0.833 against
        # a spoken "cross" and "CustomerXM" 0.889 against "customer", well over
        # the 0.82 threshold. Listing them turns "we can cross that bridge" into
        # "we can CrossXM that bridge". They reach the same spelling through
        # their replacement pairs below, which match exactly and cannot misfire.
        # CoreXM only survives here because "core" scores 0.800 and misses.
        "Qualtrics", "CoreXM",
        "XM Discover", "XM Directory", "Stats iQ", "Text iQ",
        # Platform features, named the way the support site titles them. All
        # multi-word on purpose: the single-word ones ("dashboard", "quota",
        # "distribution", "widget", "ticket", "branch") are ordinary English
        # that a vocabulary entry would recase mid-sentence.
        "Survey Flow", "Display Logic", "Skip Logic", "Embedded Data",
        "Piped Text", "Question Block", "Matrix Table", "Constant Sum",
        "Net Promoter Score", "Contact List", "Anonymous Link",
        "Employee Lifecycle", "Ad Hoc Employee Research",
        # Measures
        "NPS", "eNPS", "CSAT", "CES",
        # The product-management vocabulary
        "OKR", "KPI", "PRD", "MVP", "GTM", "QBR", "ARR", "MRR", "SLA", "SLO",
        "UAT", "RFP", "POC", "CSM", "SDK", "API", "SSO", "SAML", "SCIM",
        "GDPR", "HIPAA", "FedRAMP", "PII",
        # Tools that come up by name in every other sentence. Anything that is
        # also an ordinary word stays out: a vocabulary entry for "Slack" or
        # "Zoom" recases "some slack in the timeline" and "zoom in on the
        # funnel", and the model already spells those right as products.
        # "Tableau" is out for the same reason: it scores 0.833 against a
        # spoken "table", so it rewrites "let us table that".
        "Jira", "Figma", "Miro", "Salesforce", "Looker",
        "Databricks", "Mixpanel", "Pendo", "Okta", "ServiceNow", "Zendesk",
        "HubSpot", "Marketo", "Datadog", "PagerDuty", "GitHub", "Airtable",
        "Asana", "Smartsheet", "BigQuery", "Redshift", "Kubernetes",
    ),
    replacements=(
        # The company's own name is the one it gets wrong most.
        ("quality tricks", "Qualtrics"),
        ("quall tricks", "Qualtrics"),
        ("qual tricks", "Qualtrics"),
        ("qualtricks", "Qualtrics"),
        ("qualtrix", "Qualtrics"),
        # Spelled letters the model writes apart, joined the way the product is
        # actually written. These run before auto-format, so they win over the
        # generic acronym rule that would give "XM" alone.
        ("ex em", "XM"),
        ("core x m", "CoreXM"),
        ("customer x m", "CustomerXM"),
        ("employee x m", "EmployeeXM"),
        ("brand x m", "BrandXM"),
        ("cross x m", "CrossXM"),
        ("x m discover", "XM Discover"),
        ("x m directory", "XM Directory"),
        ("stats i q", "Stats iQ"),
        ("text i q", "Text iQ"),
        # Measures said aloud
        ("see sat", "CSAT"),
        ("sea sat", "CSAT"),
        ("e n p s", "eNPS"),
        # Product-management shorthand
        ("a b test", "A/B test"),
        ("a b testing", "A/B testing"),
        ("p zero", "P0"),
        ("p one", "P1"),
        ("p two", "P2"),
        ("p three", "P3"),
        ("sev one", "Sev1"),
        ("sev two", "Sev2"),
        ("sock two", "SOC 2"),
        ("pipe text", "Piped Text"),
        # Longest first: pairs apply in order, so "three sixty" would otherwise
        # match inside "three sixty five" and leave "360 five".
        ("three sixty five", "365"),
        ("three sixty", "360"),
        ("fed ramp", "FedRAMP"),
        ("single sign on", "single sign-on"),
        ("road map", "roadmap"),
        ("back log", "backlog"),
    ),
)

PACKS: dict[str, Pack] = {p.id: p for p in (QUALTRICS,)}


def catalog() -> list[dict]:
    """Every pack, with its terms, for the settings page to render and browse."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "vocabulary": list(p.vocabulary),
            "replacements": [{"from": a, "to": b} for a, b in p.replacements],
        }
        for p in PACKS.values()
    ]


def unknown_ids(ids) -> list[str]:
    """Pack ids that do not exist, so config validation can name them."""
    return sorted({str(i) for i in ids or []} - set(PACKS))


def merge(
    enabled, vocabulary: list[str] | None, replacements: list[dict] | None
) -> tuple[list[str], list[dict]]:
    """The user's dictionary with every enabled pack folded in behind it.

    User entries lead, which is what makes them win: replacements are applied
    in order, so a personal fix rewrites the text before a pack's pair can,
    and vocabulary is deduplicated with the user's spelling already present.
    Unknown ids are skipped rather than raising, so a config naming a pack
    that a later version dropped still runs.
    """
    vocab = list(vocabulary or [])
    pairs = list(replacements or [])
    for pack_id in enabled or []:
        pack = PACKS.get(str(pack_id))
        if pack is None:
            continue
        vocab.extend(pack.vocabulary)
        pairs.extend({"from": a, "to": b} for a, b in pack.replacements)
    return vocab, pairs
