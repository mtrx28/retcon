"""Claim filter for the science extractor: drop sentences that are not claims.

An abstract sentence becomes a claim node only if `reject_reason(s)` is None. Rules, in order (each returns
a short reason so the audit and the tests can say *why* something was dropped):

  section_label     a leading label is stripped first (BACKGROUND:, RESULT(S):, "Abstract"); a METHODS /
                    OBJECTIVE / AIM / PURPOSE / DESIGN / SETTING / PROCESS label marks it as not a finding
  too_short         fewer than MIN_WORDS words
  truncated         ends mid-thought (a dangling abbreviation like "vs." / "et al." or no closing punctuation)
  author_list       author names, initials, affiliations, e-mail
  no_verb           no finite verb: a list of sources, a title, a noun phrase
  aim_framing       "this study aims...", "the purpose of ... was", "we sought to": says what the paper set
                    out to do, not what it found (kept if the same sentence also reports a result)
  describes_itself  "in this review we describe ...", "the guideline provides ...", "is the first trial to":
                    says what the document is or does, not what was found
  methods           "cells were incubated ...", "patients were enrolled": procedure, not a finding

Deterministic, no model calls. Conservative on purpose: a rejected sentence costs one candidate (there are
usually many); a kept non-claim shows up as an author list in a demo. Measured against a hand-labelled
corpus in tests/data/claim_filter_cases.json (tests/queries/test_claim_filter.py).
"""
import re

MIN_WORDS = 7

_LABEL = re.compile(
    r"^\s*(?:abstract\b[:.\s-]*)?(?P<label>background|introduction|context|objectives?|aims?|purpose|"
    r"design|setting|settings|participants|patients|methods?|materials and methods|methodology|"
    r"results?|findings|conclusions?|discussion|significance|importance|interpretation)\s*[:\-]\s*", re.I)
_NOT_A_FINDING = {"objective", "objectives", "aim", "aims", "purpose", "design", "setting", "settings",
                  "participants", "patients", "method", "methods", "materials and methods", "methodology"}
_LEADING_ABSTRACT = re.compile(r"^\s*abstract\b[:.\s-]*", re.I)
_CAPS_LABEL = re.compile(r"^\s*(?P<label>[A-Z][A-Z0-9 /()&,\-]{2,40}):\s+")
_CAPS_NOT_FINDING = ("OBJECTIVE", "AIM", "PURPOSE", "DESIGN", "SETTING", "PROCESS", "METHOD", "MATERIAL",
                     "PARTICIPANT", "PATIENT", "INTERVENTION", "STUDY QUESTION", "STUDY DESIGN")
RESULT_LABELS = {"results", "result", "findings", "conclusion", "conclusions"}

_ABBREV_END = re.compile(
    r"(?:\b(?:vs|et al|e\.g|i\.e|cf|approx|fig|figs|no|dr|prof|ca|resp|incl|ref|refs|st)\.)$", re.I)
_AFFIL = re.compile(r"\b(university|universit[ée]|department of|dept\.|institute of|school of|faculty of|"
                    r"college of|hospital|laborator(?:y|ies)|centre|center for|e-?mail)\b|@", re.I)
_STOP = {"the", "of", "in", "is", "are", "was", "were", "that", "which", "and", "to", "by", "with", "for", "on",
         "as", "from", "this", "these", "it", "be", "has", "have", "an", "a", "or", "not", "at"}

_AUX = {"is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "can", "could", "may", "might",
        "will", "would", "should", "must", "does", "do", "did", "shall"}
_VERBS = set("""show shows showed shown find finds found demonstrate demonstrates demonstrated reveal reveals
revealed indicate indicates suggest suggests suggested identify identifies identified report reports reported lead
leads led cause causes caused play plays played require requires act acts bind binds bound occur occurs remain
remains represent represents include includes provide provides form forms exert exerts express expresses regulate
regulates promote promotes inhibit inhibits increase increases decrease decreases reduce reduces enhance enhances
induce induces mediate mediates contribute contributes affect affects improve improves determine determines depend
depends interact interacts target targets control controls support supports activate activates suppress
suppresses undergo undergoes develop develops appear appears seem seems become becomes encode encodes protect
protects trigger triggers drive drives prevent prevents facilitate facilitates modulate modulates correlate
correlates associate associates link links impair impairs attenuate attenuates elevate elevates alter alters
change changes produce produces release releases degrade degrades stimulate stimulates mean means make makes give
gives take takes function functions participate participates operate operates generate generates maintain
maintains hypothesis outperform outperforms outperformed achieve achieves exhibit exhibits possess possesses
confer confers enable enables allow allows involve involves comprise comprises consist consists highlight
highlights highlighted engulf engulfs engulfed implicate implicates""".split())

# words that are verbs or nouns; alone, in a short sentence without an auxiliary, they make a title not a claim
_AMBIGUOUS = {"control", "controls", "change", "changes", "function", "functions", "link", "links", "target",
              "targets", "support", "supports", "form", "forms", "release", "mean", "means", "hypothesis",
              "act", "acts", "drive", "drives", "produce", "produces", "regulate", "regulates"}
_TITLE_TAIL = re.compile(r"[IVX]{1,5}\.?$")

_AIM = re.compile(
    r"\b(?:(?:the\s+)?(?:aim|purpose|objective|goal|intent)s?\s+(?:of|was|is|were|are)\b"
    r"|(?:this|the|the present|the current|our)\s+(?:study|studies|review|paper|article|work|investigation|"
    r"analysis|report|guideline|trial)\s+(?:\w+ly\s+)?(?:aims?|aimed|seeks?|sought|was designed|is designed|"
    r"focus(?:es|ed)|intends?|intended|will|attempts?|attempted|hypothesi[sz]ed|hypothesi[sz]es|evaluates?|"
    r"evaluated|examines?|examined|investigates?|investigated|describes?|described|discusses?|discussed|"
    r"reviews?|reviewed|summari[sz]es?|summari[sz]ed|explores?|explored|assesses?|assessed)\b"
    r"|we\s+(?:aim|aimed|sought|seek|hypothesi[sz]ed|set out|propose to|intend|review|discuss|summari[sz]e)\b"
    r"|(?:was|were)\s+(?:hypothesi[sz]ed|designed|aimed)\b"
    r"|(?:^|[.;:]\s+)to\s+(?:investigate|understand|evaluate|determine|assess|examine|explore|identify|"
    r"clarify|elucidate|compare|test|study|analy[sz]e|reveal|characteri[sz]e)\b)", re.I)
_DESCRIBES_ITSELF = re.compile(
    r"(?:\bin\s+this\s+(?:study|review|paper|article|work|report|investigation)\s*,?\s*we\s+"
    r"(?:\w+ly\s+)?(?:describe|developed|develop|present|review|summari[sz]e|discuss|introduce|propose|outline|"
    r"provide|build|built|constructed|establish)\b"
    r"|\b(?:the|this|our)\s+(?:current\s+|present\s+)?(?:guidelines?|review|study|trial|paper|article|"
    r"database|tool|platform|resource|consensus|statement)\s+(?:is|provides?|contains?|presents?|offers?|"
    r"includes?|(?:\w+ly\s+)?summari[sz]es|covers?|outlines?)\b"
    r"|\b(?:is|was)\s+the\s+first\b[^.]{0,90}\b(?:trial|study|analysis|review|database)\b"
    r"|\b(?:is|was)\s+the\s+\w+\s+(?:volume|edition|part|chapter|release|version)\b"
    r"|\b(?:is|are)\s+(?:calculated|computed|defined)\s+(?:to|as|by)\b"
    r"|\b(?:is|are|was|were)\s+described\s+in\b"
    r"|^it\s+(?:\w+ly\s+)?(?:summari[sz]es|reviews|analy[sz]es|discusses|describes|outlines)\b"
    r"|^focusing on\b|\bthis\s+(?:review|article|paper)\s+(?:\w+ly\s+)?(?:summari[sz]es|discusses|describes)\b)",
    re.I)
_RESULT_VERB = re.compile(r"\b(show(?:s|ed|n)?|demonstrat\w+|found|find(?:s|ings?)?|reveal(?:s|ed)|indicat\w+|"
                          r"conclude[sd]?|identified|observed|result(?:s|ed)?\s+in)\b", re.I)
_METHODS = re.compile(
    r"\b(?:was|were)\s+(?:used|performed|conducted|measured|assessed|collected|obtained|recruited|enrolled|"
    r"randomi[sz]ed|divided|treated|incubated|cultured|stained|induced|analy[sz]ed|calculated|evaluated|"
    r"established|isolated|extracted|purchased|prepared|screened|retrospectively|included|excluded|"
    r"identified as important|applied|employed|explored by|carried out|utili[sz]ed|undertaken|convened|"
    r"detected by|confirmed by|described)\b"
    r"|^(?:we|the\s+authors?)\s+(?:searched|screened|enrolled|recruited|collected|retrieved|"
    r"retrospectively|performed|conducted|analy[sz]ed|included|used|applied|reviews?)\b",
    re.I)


_BARE_LABEL = re.compile(r"^(?P<label>Results?|Conclusions?|Background|Methods?|Objectives?|Purpose)\s+(?=[A-Z0-9])")
_BARE_CAPS_LABEL = re.compile(r"^(?P<label>RESULTS?|CONCLUSIONS?|BACKGROUND|METHODS?|OBJECTIVES?|PURPOSE)\s+")

# Procedure statements are not findings even when they mention a result verb ("were used to demonstrate").
_PROCEDURE = re.compile(
    r"\b(?:was|were|is|are)\s+(?:randomly\s+)?(?:assigned|introduced|carried out|performed|conducted)\b"
    r"|\b(?:was|were|is|are)\s+(?:used|applied|employed|introduced)\s+(?:to|into|for|in)\b"
    r"|\bthe\s+trial\s+was\b|^\d+\)\s", re.I)
_BUILT_A_RESOURCE = re.compile(
    r"\bwe\s+(?:developed|built|constructed|created|established)\s+(?:a|an)\s+(?:\w+\s+){0,3}"
    r"(?:database|web\s?site|tool|platform|resource|server|software|pipeline|framework)\b"
    r"|^this\s+(?:review|article|paper|study)\s+(?:addresses|presents|provides|offers|aims)\b", re.I)


def clean(sentence: str) -> tuple[str, str | None]:
    """Strip a leading section label. Returns (text, label lower-cased or None)."""
    s = sentence.strip()
    m = _BARE_LABEL.match(s) or _BARE_CAPS_LABEL.match(s)
    if m:
        return s[m.end():].strip(), m.group("label").lower()
    m = _LABEL.match(s)
    if m:
        return s[m.end():].strip(), m.group("label").lower()
    m = _CAPS_LABEL.match(s)
    if m:
        lab = m.group("label").strip()
        if any(k in lab for k in _CAPS_NOT_FINDING):
            kind = "objective"
        elif any(k in lab for k in ("RESULT", "FINDING", "CONCLUSION")):
            kind = "results"
        else:
            kind = lab.lower()
        return s[m.end():].strip(), kind
    return _LEADING_ABSTRACT.sub("", s).strip(), None


def _words(s):
    return re.findall(r"[A-Za-z][A-Za-z'’\-]*", s)


def _has_verb(s: str) -> bool:
    ws = _words(s)
    if len(ws) <= 12 and not any(w.lower() in _AUX for w in ws):
        # a short sentence needs a verb that is not also a common noun
        pool = [w for w in ws if w.lower() not in _AMBIGUOUS]
        if _TITLE_TAIL.search(s.strip()):
            return False
        ws = pool
    for i, t in enumerate(ws):
        low = t.lower()
        if i > 0 and t[0].isupper() and not t.isupper() and low not in _AUX:
            continue                                   # a proper noun mid-sentence is not a verb
        if low in _AUX or low in _VERBS:
            return True
        if len(low) > 4 and low.endswith("ed") and (i == 0 or t.islower()):
            return True
        if len(low) > 5 and low.endswith("ing") and t.islower():   # "impairing", "promoting": a clause
            return True
    return False


def _looks_like_names(s: str) -> bool:
    toks = re.findall(r"[A-Za-z][A-Za-z'’.\-]*", s)
    if len(toks) < 2:
        return False
    capped = sum(1 for t in toks if t[0].isupper())
    stop = sum(1 for t in toks if t.lower() in _STOP)
    return capped / len(toks) >= 0.7 and stop <= 1


def reject_reason(sentence: str) -> str | None:
    """None if the sentence is an acceptable claim, else the name of the first rule that rejects it."""
    s, label = clean(sentence)
    if label in _NOT_A_FINDING or label == "objective":
        return "section_label"
    if len(_words(s)) < MIN_WORDS:
        return "too_short"
    if _ABBREV_END.search(s) or not re.search(r"[.!?)\]\"'”’]$", s):
        return "truncated"
    if _AFFIL.search(s) or _looks_like_names(s):
        return "author_list"
    if not _has_verb(s):
        return "no_verb"
    reports_result = _RESULT_VERB.search(s)
    if _AIM.search(s) and not reports_result:
        return "aim_framing"
    if _PROCEDURE.search(s):
        return "methods"
    if _BUILT_A_RESOURCE.search(s):
        return "describes_itself"
    if _DESCRIBES_ITSELF.search(s) and not reports_result:
        return "describes_itself"
    if _METHODS.search(s) and not reports_result:
        return "methods"
    return None


def is_claim(sentence: str) -> bool:
    return reject_reason(sentence) is None
