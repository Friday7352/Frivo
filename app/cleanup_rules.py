"""
NEW (1.6.0): Clean up without AI.

When no AI can be reached (no OpenAI key, Ollama off, nothing built in),
Clean up still tidies an English message with plain rules, on the CPU, in
a few milliseconds:

  * spelling, from a dictionary of everyday English (symspellpy's word
    list), only for words it doesn't know, and only when one fix is clearly
    the likely one: "teh" -> "the", "recieve" -> "receive"
  * contractions typed without the apostrophe: "dont" -> "don't",
    "im" -> "I'm"; and "i" -> "I"
  * a few phrases that are always a slip: "could of" -> "could have",
    "alot" -> "a lot"
  * a word typed twice ("the the"), spacing around punctuation, a capital
    at the start of each sentence, and a full stop or question mark at the
    end when there's none

What it never touches: voice tags ([laughs]), slang and text-speak (lol,
ngl, gonna), your Tag words, names (a capital in the middle of a sentence),
words in capitals, stretched words ("sooo"), numbers, links, @names and
emoji. It can't work out what you *meant*: a misheard word that is still a
real word stays. That's what the AI is for.

Nothing here is run from the network: the word list ships with symspellpy.
The list is loaded the first time it's needed (about two seconds and
120 MB of memory), and spelling is skipped if symspellpy isn't installed.
"""

import os
import re
import threading

# Never "corrected": text-speak, slang and words people mean as typed.
SLANG = set("""
lol lmao lmfao rofl lul kek xd xdd heh hehe haha hahaha hah teehee
omg omfg wtf wth ffs smh tbh tbf ngl idk idc idgaf imo imho irl brb btw bc cuz coz cos tho thx ty tysm np
pls plz plox fr frfr ong rn atm asap jk ikr iirc afaik fyi gg ggs wp glhf afk gtg g2g ttyl nvm ofc
ok okay k kk mkay yeah yea ya yah yep yup nah nope naw ye yee yay yas yass aye
bro bruh bra brah dude dudes fam homie sis bestie babe bae hun boi gurl gal
gonna wanna gotta kinda sorta dunno lemme gimme outta lotta whatcha gotcha betcha y'all yall ain't aint innit
u ur r ya yo sup wassup whaddup hiya heya ello
vr vrc vrchat discord twitch youtube tiktok insta reddit steam quest pcvr fbt hmm hmmm mhm mmm uh um uhh umm erm ah ahh oh ohh ooh oof ouch ow yikes welp whoa woah wow meh eh huh
ima imma finna tryna boutta
rizz sus mid cap nocap bet vibe vibes vibing lowkey highkey deadass periodt slay yeet poggers pog based cringe goated
emote emotes avi avis avatar avatars
""".split())

# Contractions typed without the apostrophe. Only ones that can't be
# another word: "its", "ill", "id", "were", "well", "lets", "hell" and
# "shell" are real words, so they're left alone.
CONTRACTIONS = {
    "im": "I'm", "ive": "I've", "dont": "don't", "doesnt": "doesn't", "didnt": "didn't",
    "cant": "can't", "wont": "won't", "isnt": "isn't", "arent": "aren't", "wasnt": "wasn't",
    "werent": "weren't", "havent": "haven't", "hasnt": "hasn't", "hadnt": "hadn't",
    "couldnt": "couldn't", "shouldnt": "shouldn't", "wouldnt": "wouldn't", "mustnt": "mustn't",
    "neednt": "needn't", "youre": "you're", "theyre": "they're", "thats": "that's",
    "whats": "what's", "wheres": "where's", "whos": "who's", "hows": "how's", "theres": "there's",
    "heres": "here's", "hes": "he's", "shes": "she's", "weve": "we've", "youve": "you've",
    "theyve": "they've", "youll": "you'll", "theyll": "they'll", "itll": "it'll",
    "thatll": "that'll", "youd": "you'd", "theyd": "they'd", "shouldve": "should've",
    "couldve": "could've", "wouldve": "would've", "mightve": "might've", "whatre": "what're",
    "everyones": "everyone's", "nobodys": "nobody's", "somebodys": "somebody's",
}

# Always a slip, whatever the sentence.
PHRASES = [
    (r"\b(could|should|would|must|might)\s+of\b", r"\1 have"),
    (r"\balot\b", "a lot"),
    (r"\bnoone\b", "no one"),
    (r"\beverytime\b", "every time"),
    (r"\binfact\b", "in fact"),
    (r"\batleast\b", "at least"),
    (r"\baswell\b", "as well"),
    (r"\bthankyou\b", "thank you"),
    (r"\beachother\b", "each other"),
    (r"\bincase\b", "in case"),
    (r"\bnevermind\b", "never mind"),
    (r"\bto\s+be\s+honest\b", "to be honest"),
]

# A word typed twice is only taken out for these: "had had" and "that that"
# can be right.
DOUBLES = set("the a an to of and in on at for with is it i my your you we they he she this".split())

QUESTION_START = set("""who what when where why how which whose whom do does did is are was were am can could
would will should shall may might have has had isn't aren't wasn't don't doesn't didn't can't won't
couldn't wouldn't shouldn't haven't hasn't what's where's who's how's whats wheres whos hows""".split())

# Words that can come before a question without being part of it.
LEAD_INS = set("hey hi hello yo so ok okay and but um uh wait oh well also anyway like bro dude".split())

# Pieces of a message, in order. Anything not matched is passed through.
_TOKEN_RE = re.compile(
    r"(?P<tag>\[[^\[\]\n]{1,60}\])"
    r"|(?P<url>(?:https?://|www\.)\S+)"
    r"|(?P<handle>[@#][\w.]+)"
    r"|(?P<word>[A-Za-z]+(?:['’][A-Za-z]+)*)"
    r"|(?P<num>\d[\d,.:/]*\w*)"
    r"|(?P<space>\s+)"
    r"|(?P<other>.)",
    re.S,
)

_SPELL = {"engine": None, "tried": False}
_SPELL_LOCK = threading.Lock()


def spelling_engine():
    """symspellpy with its English word list, loaded once. None if it
    isn't installed (Clean up then does everything but spelling)."""
    with _SPELL_LOCK:
        if _SPELL["tried"]:
            return _SPELL["engine"]
        _SPELL["tried"] = True
        try:
            import symspellpy
            from symspellpy import SymSpell
            folder = os.path.dirname(symspellpy.__file__)
            engine = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
            if not engine.load_dictionary(os.path.join(folder, "frequency_dictionary_en_82_765.txt"), 0, 1):
                return None
            _SPELL["engine"] = engine
        except Exception:
            _SPELL["engine"] = None
        return _SPELL["engine"]


def warm_up():
    """Loads the word list in the background, so the first clean-up
    without AI doesn't wait for it."""
    threading.Thread(target=spelling_engine, daemon=True).start()


def _match_case(original, fixed):
    if original.isupper() and len(original) > 1:
        return fixed.upper()
    if original[:1].isupper():
        return fixed[:1].upper() + fixed[1:]
    return fixed


def _is_stretched(word):
    return re.search(r"([a-z])\1\1", word.lower()) is not None


def _fix_spelling(word, engine, protected):
    """The word, or its likely spelling. Only words the dictionary doesn't
    know, and only one clear fix."""
    lower = word.lower()
    if (engine is None or len(word) < 3 or lower in protected or lower in SLANG
            or "'" in word or "’" in word or _is_stretched(word)):
        return word
    if word.isupper():                 # ASAP, NASA, LOL
        return word
    if word[1:] != word[1:].lower():   # McDonald, iPhone
        return word
    if lower in engine.words:
        return word
    from symspellpy import Verbosity
    max_distance = 2 if len(word) >= 6 else 1
    found = engine.lookup(lower, Verbosity.CLOSEST, max_edit_distance=max_distance)
    if not found:
        return word
    best = found[0]
    # Two equally close fixes that are both common: no clear answer.
    if len(found) > 1 and found[1].distance == best.distance and found[1].count > best.count / 3:
        return word
    if best.count < 50_000:            # a rare word is a worse guess than the typo
        return word
    return _match_case(word, best.term)


def _protected_words(extra):
    words = set()
    for item in extra or ():
        for part in re.findall(r"[A-Za-z']+", str(item or "")):
            words.add(part.lower())
    return words


def clean_up(text, protect=()):
    """
    The message, tidied by rules. `protect` is more words to leave alone
    (your Tag words, say). Returns (text, changed).
    """
    original = text or ""
    if not original.strip():
        return original, False
    protected = _protected_words(protect)
    engine = spelling_engine()

    # The always-a-slip phrases first, so "alot" isn't spell-checked into "lot".
    text = original
    for pattern, replacement in PHRASES:
        text = re.sub(pattern, lambda m: _match_case(m.group(0), m.expand(replacement)), text, flags=re.I)

    tokens = [(m.lastgroup, m.group()) for m in _TOKEN_RE.finditer(text)]

    # Which words start a sentence: the first word, and the first after . ! ?
    starts = set()
    expect = True
    for i, (kind, value) in enumerate(tokens):
        if kind == "word":
            if expect:
                starts.add(i)
            expect = False
        elif kind == "other" and value in ".!?":
            expect = True
        elif kind in ("url", "handle", "num"):
            expect = False

    out = []
    for i, (kind, value) in enumerate(tokens):
        if kind != "word":
            out.append((kind, value))
            continue
        lower = value.lower()
        if lower == "i":
            value = "I"
        elif lower in CONTRACTIONS and lower not in protected:
            value = _match_case(value, CONTRACTIONS[lower]) if lower != "im" else "I'm"
        elif re.fullmatch(r"i['’](m|ve|ll|d)", lower):
            value = "I" + value[1:]
        else:
            # A capital in the middle of a sentence is a name: left alone.
            if value[:1].isupper() and i not in starts:
                out.append((kind, value))
                continue
            value = _fix_spelling(value, engine, protected)
        out.append((kind, value))

    # A word typed twice ("the the"): the second one goes.
    cleaned = []
    last_word = None
    for kind, value in out:
        if kind == "word":
            if last_word is not None and value.lower() == last_word.lower() and value.lower() in DOUBLES:
                # Drop it and the space before it.
                if cleaned and cleaned[-1][0] == "space":
                    cleaned.pop()
                continue
            last_word = value
        elif kind not in ("space",):
            last_word = None
        cleaned.append((kind, value))

    # Capitals at the start of each sentence.
    result = []
    expect = True
    for kind, value in cleaned:
        if kind == "word":
            if expect and value[:1].islower():
                value = value[:1].upper() + value[1:]
            expect = False
        elif kind == "other" and value in ".!?":
            expect = True
        elif kind in ("url", "handle", "num"):
            expect = False
        result.append(value)
    text = "".join(result)

    # Spacing: one space between words, none before , . ! ? and one after.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])(?=\s|$)", r"\1", text)
    text = re.sub(r"([,;!?])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"(?<=[a-z])\.(?=[A-Z][a-z])", ". ", text)   # "ok.So" but not "e.g." or "1.5"
    text = text.strip()

    text = _end_punctuation(text)
    return text, text != original.strip()


def _end_punctuation(text):
    """A full stop, or a question mark for a question, when the message
    ends without one. Not after a tag, an emoji, a link or text-speak."""
    if not text or re.search(r"[.!?…)\]:;~\"'*]$", text):
        return text
    if re.search(r"(https?://|www\.)\S+$", text):
        return text
    last = re.findall(r"[A-Za-z']+", text)
    if not last or last[-1].lower() in SLANG:
        return text
    if not re.search(r"[A-Za-z0-9]$", text):   # ends in an emoji or a symbol
        return text
    # The last sentence: does it ask something?
    sentence = re.split(r"(?<=[.!?])\s+", text)[-1]
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", sentence)]
    if len(words) < 2:
        return text
    # "Hey, what's up" asks too: past a greeting or a filler word.
    while len(words) > 1 and words[0] in LEAD_INS:
        words = words[1:]
    return text + ("?" if words[0] in QUESTION_START else ".")
