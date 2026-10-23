"""One warning under the verdict for whatever the manipulation checks found.

Three code-blind checks follow the accusation: the reversal check (``decoder/reversal.py``,
marks read against the direction every copy almost surely carries), the erasure check
(``decoder/erasure.py``, marks missing where the colluders' copies probably agree) and the
contradiction check (``decoder/contradiction.py``, a clear read that names nobody). Whatever
they find becomes one block of text, shown under the verdict in the web page, the CLI summary
and the berita acara and kept in the JSON notes:

1. one primary sentence: the evidence was probably changed by someone who knows TAPAK, and
   what was found (each finding once, in the order reversal, erasure, contradiction);
2. the possible causes, merged (what a coalition did, a larger coalition, a reading problem);
3. the rate: on honest evidence each check sounds with probability at most about 10^-3,
   with the numbers of the checks that sounded (the three rates are not split, so by the union
   bound the block itself can appear on honest evidence with probability up to about 3 x 10^-3);
4. that it is only a warning: nobody is named because of it, and the verdict, the thresholds
   and the scores do not change.

The text never contains a name, a copy number or a recipient: the checks never see a codeword.
"""

from __future__ import annotations

from tapak.decoder.contradiction import CONTRADICTION_NOTE, ContradictionCheck, format_bound
from tapak.decoder.erasure import ERASURE_NOTE, ErasureCheck, format_rate
from tapak.decoder.reversal import REVERSAL_MAX_COALITION, REVERSAL_NOTE, ReversalCheck

# Every merged warning starts with this; ``is_manipulation_note`` recognises it.
MANIPULATION_LEAD = "bukti kemungkinan diubah oleh orang yang memahami TAPAK"
# The second and third sentences start with these (the web page sets the first sentence in bold
# and starts each later sentence on its own line).
CAUSES_LEAD = "Kemungkinan penyebab: "
RATE_LEAD = "Pada bukti jujur "
ONLY_A_WARNING = ("Ini hanya peringatan: tidak ada nama yang disebut karenanya, dan putusan, ambang, serta skor tidak "
                  "berubah")


def _flagged(check):
    return check if check is not None and check.flagged else None


def manipulation_note(erasure: ErasureCheck | None, contradiction: ContradictionCheck | None,
                      reversal: ReversalCheck | None = None, statistics: bool = True) -> str | None:
    """The merged warning for the checks that sounded, or None when none did (module docstring).

    ``statistics=False`` leaves out the statistic of each check (its ``text()``), for a page that
    shows those statistics next to the warning anyway (the web result's validity box); every
    other word, including the per-document caveat of the erasure check, stays."""
    rev, era, con = _flagged(reversal), _flagged(erasure), _flagged(contradiction)
    if rev is None and era is None and con is None:
        return None
    findings = [text for check, text in ((rev, REVERSAL_NOTE), (era, ERASURE_NOTE), (con, CONTRADICTION_NOTE))
                if check is not None]
    verbs = [verb for verb, on in (("menghapus", era), ("membalik", rev or con), ("mengacak", con)) if on is not None]
    if len(verbs) == 1:
        did = verbs[0]
    else:
        did = ", ".join(verbs[:-1]) + (", atau " if len(verbs) > 2 else " atau ") + verbs[-1]
    causes = [f"koalisi pemegang dua salinan atau lebih {did} tanda di tempat salinannya sama"
              + (", atau satu salinan membalik semua tandanya" if rev or con else "")]
    if rev or con:
        larger = con.coalition if con is not None else REVERSAL_MAX_COALITION
        if rev is not None:  # the reversal bound covers coalitions of at most three, whatever c
            larger = min(larger, REVERSAL_MAX_COALITION)
        causes += [f"koalisi lebih dari {larger} orang", "masalah pembacaan bukti"]
    cause_text = causes[0] if len(causes) == 1 else "; ".join(causes[:-1]) + "; atau " + causes[-1]
    details = []
    if rev is not None and statistics:
        details.append(f"pola tanda terbalik: {rev.text()}")
    if era is not None:
        stat = f"{era.text()}, " if statistics else ""
        details.append(f"pola penghapusan: {stat}untuk dokumen tertentu laju alarm palsunya dapat sampai beberapa persen")
    if con is not None:
        details.append(f"bacaan jelas tanpa nama: koalisi paling banyak {con.coalition} penerima yang tidak mengubah "
                       f"tanda di tempat salinannya sama lolos dengan peluang terbukti paling besar "
                       f"{format_bound(con.log10_bound)}, bila laju salah bacaan tidak melebihi perkiraannya")
    rates = [c.alarm_rate for c in (rev, era) if c is not None] + ([con.rate] if con is not None else [])
    rate = max(rates)
    which = "pemeriksaan ini" if len(findings) == 1 else "setiap pemeriksaan ini"
    detail_text = f" ({'; '.join(details)})" if details else ""
    return (f"{MANIPULATION_LEAD}: {'; '.join(findings)}. {CAUSES_LEAD}{cause_text}. {RATE_LEAD}"
            f"{which} memberi peringatan dengan peluang paling besar sekitar {format_rate(rate)}, rata-rata atas "
            f"dokumen, bila derau bacaan tidak bergantung pada kode{detail_text}. {ONLY_A_WARNING}")


def is_manipulation_note(note: str) -> bool:
    """True for a warning written by :func:`manipulation_note`."""
    return note.startswith(MANIPULATION_LEAD)


def manipulation_parts(note: str) -> list[str]:
    """The four sentences of a merged warning (what was found, the causes, the rate, that it is
    only a warning), each ending with a full stop, so a page can set them on their own lines;
    ``[note]`` for any other note or a warning whose sentences cannot be found."""
    if not is_manipulation_note(note):
        return [note]
    cuts = [note.find(". " + lead) for lead in (CAUSES_LEAD, RATE_LEAD, ONLY_A_WARNING)]
    if any(c < 0 for c in cuts) or cuts != sorted(cuts):
        return [note]
    starts = [0] + [c + 2 for c in cuts]
    ends = [c + 1 for c in cuts] + [len(note)]
    parts = [note[a:b].strip() for a, b in zip(starts, ends)]
    return [part if part.endswith(".") else part + "." for part in parts]


__all__ = ["CAUSES_LEAD", "MANIPULATION_LEAD", "ONLY_A_WARNING", "RATE_LEAD", "is_manipulation_note",
           "manipulation_note", "manipulation_parts"]
