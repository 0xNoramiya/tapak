# Pola tanda terbalik, aturan gabungan pola penghapusan, dan aturan skor dua sisi

Riset untuk tiga perubahan:

1. **Pemeriksaan pola tanda terbalik** (`tapak/decoder/reversal.py`). Dua statistik tanpa kode penerima: z pilot, jumlah pilot dekoder latar dari semua halaman gambar, dan z tanda, A / akar(B) atas bacaan gabungan dengan A = jumlah w (2p - 1)(2y - 1) dan B = jumlah w^2 (2p - 1)^2. Peringatan bila salah satunya paling besar -3,90 (laju 10^-3 dibagi dua, batas sub-Gauss exp(-t^2 / 2)).
2. **Pola penghapusan dengan dua statistik** (`tapak/decoder/erasure.py`). Z dengan aturan latar "pola" dan Z dengan "semua", masing-masing dengan ambang -3,29 (laju 10^-3 dibagi dua).
3. **Aturan skor dua sisi** (riset saja, tidak dipasang). Jatah eps tahap 1 dibagi ke kedua ekor: salinan disebut bila skornya paling sedikit Z(eps1 / 2) atau paling besar -Z(eps1 / 2).

Ketiga peringatan digabung menjadi satu blok di bawah putusan (`tapak/decoder/manipulation.py`). Peringatan tidak menyebut siapa pun dan tidak mengubah putusan, ambang, atau skor. Semua dokumen dan penerima fiktif; semua foto dan cetakan sintetis.

## Protokol

Protokol, benih, media, laju, aturan rekomendasi, dan analisis ditulis di docstring `ukur.py` dan dicatat di git sebelum benih uji dijalankan. Benih pengembangan (9401 sampai 9415) hanya dipakai untuk uji coba kering (`hasil/dev.jsonl`); tidak ada laju, ambang, atau aturan yang dipilih darinya. Benih uji (9601 sampai 9640) baru: tidak dipakai `research/sepakat`, `research/kontradiksi`, atau protokol lain.

## Uji coba kering (benih pengembangan)

158 pelacakan, 0 tuduhan salah. Bukti jujur: tidak ada peringatan; z tanda terendah 4,5 pada salinan bertanda (cetakan). Pada induk tanpa tanda surat telegram skema v1 z tanda -2,97 dan -3,04 (tangkapan layar dan foto dokumen yang sama): bacaan geser induk sebagian ditentukan tipografinya, jadi satu dokumen tanpa tanda punya pusat z tandanya sendiri, seperti pusat Z pola penghapusan. Pembalikan ditandai pada 4 dari 4 PDF, tangkapan layar, dan foto, dan 3 dari 4 cetakan dua halaman; `buang-acak` (pola latar dibuang, geser yang sama diacak) lolos dari semua pemeriksaan, seperti yang diperkirakan.

## Hasil

Diisi setelah benih uji dijalankan.
