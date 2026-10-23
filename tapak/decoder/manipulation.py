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
   with the numbers of the checks that sounded;
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
ONLY_A_WARNING = ("Ini hanya peringatan: tidak ada nama yang disebut karenanya, dan putusan, ambang, serta skor tidak "
                  "berubah")


def _flagged(check):
    return check if check is not None and check.flagged else None


def manipulation_note(erasure: ErasureCheck | None, contradiction: ContradictionCheck | None,
                      reversal: ReversalCheck | None = None) -> str | None:
    """The merged warning for the checks that sounded, or None when none did (module docstring)."""
    rev, era, con = _flagged(reversal), _flagged(erasure), _flagged(contradiction)
    if rev is None and era is None and con is None:
        return None
    findings = [text for check, text in ((rev, REVERSAL_NOTE), (era, ERASURE_NOTE), (con, CONTRADICTION_NOTE))
                if check is not None]
    verbs = [verb for verb, on in (("menghapus", era), ("membalik", rev or con), ("mengacak", con)) if on is not None]
    did = verbs[0] if len(verbs) == 1 else ", ".join(verbs[:-1]) + (", atau " if len(verbs) > 2 else " atau ") + verbs[-1]
    causes = [f"koalisi pemegang dua salinan atau lebih {did} tanda di tempat salinannya sama"
              + (", atau satu salinan membalik semua tandanya" if rev or con else "")]
    if rev or con:
        larger = con.coalition if con is not None else REVERSAL_MAX_COALITION
        if rev is not None:  # the reversal bound covers coalitions of at most three, whatever c
            larger = min(larger, REVERSAL_MAX_COALITION)
        causes += [f"koalisi lebih dari {larger} orang", "masalah pembacaan bukti"]
    cause_text = causes[0] if len(causes) == 1 else "; ".join(causes[:-1]) + "; atau " + causes[-1]
    details = []
    if rev is not None:
        details.append(f"pola tanda terbalik: {rev.text()}")
    if era is not None:
        details.append(f"pola penghapusan: {era.text()}, untuk dokumen tertentu laju alarm palsunya dapat sampai "
                       "beberapa persen")
    if con is not None:
        details.append(f"bacaan jelas tanpa nama: koalisi paling banyak {con.coalition} penerima yang tidak mengubah "
                       f"tanda di tempat salinannya sama lolos dengan peluang terbukti paling besar "
                       f"{format_bound(con.log10_bound)}, bila laju salah bacaan tidak melebihi perkiraannya")
    rates = [c.alarm_rate for c in (rev, era) if c is not None] + ([con.rate] if con is not None else [])
    rate = max(rates)
    which = "pemeriksaan ini" if len(findings) == 1 else "setiap pemeriksaan ini"
    return (f"{MANIPULATION_LEAD}: {'; '.join(findings)}. Kemungkinan penyebab: {cause_text}. Pada bukti jujur "
            f"{which} berbunyi dengan peluang paling besar sekitar {format_rate(rate)}, rata-rata atas dokumen, bila "
            f"derau bacaan tidak bergantung pada kode ({'; '.join(details)}). {ONLY_A_WARNING}")


def is_manipulation_note(note: str) -> bool:
    """True for a warning written by :func:`manipulation_note`."""
    return note.startswith(MANIPULATION_LEAD)


__all__ = ["MANIPULATION_LEAD", "ONLY_A_WARNING", "is_manipulation_note", "manipulation_note"]
