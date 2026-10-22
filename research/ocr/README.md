# OCR bukti gambar: varian kalimat dan pilihan kata

Varian kalimat (kanal 4) dan pilihan kata (kanal 6) adalah kata yang tercetak di halaman. Keduanya ikut terbawa ke foto, tangkapan layar, dan cetakan, sedangkan pola latar bawaan tidak sampai ke kertas. Studi ini mengukur apa yang ditambahkan pembacaan OCR (Tesseract lokal) atas halaman yang ditemukan di bukti gambar, terutama untuk salinan yang dicetak.

Semua gambar sintetis (`tapak/photos.py`, `tapak/ponsel.py`). Kamera, monitor, dan printer sungguhan belum diuji.

## Protokol

Protokol dan semua benih ditetapkan di `ukur.py` (`PROTOCOL`) sebelum pengukuran pertama dan masuk riwayat repositori lebih dulu.

* **Penerbitan.** Nota dinas dan surat telegram contoh (fiktif), masing-masing lewat `tapak issue --benih-riset BENIH --no-registry` untuk N = 20 penerima (c = 3, eps = 10^-6, skema geser dan profil latar bawaan). Arm `utama` memakai semua varian tabel frasa tiruan (`tapak semantic suggest --llm mock`, disetujui semua) dan semua titik pilihan kata tingkat A (`tapak leksikal scan`, disetujui semua). Set uji juga diterbitkan tanpa kedua kanal itu (arm `tanpa`, penerbitan bawaan) dengan benih yang sama, jadi id salinan dan kodenya sama dan foto kedua arm berbagi semua bilangan acak.
* **Dua set benih.** Set `dev` (benih riset 7301 dan 7302, benih bukti 7311) dipakai untuk memilih pengaturan OCR. Set `uji` (7401 dan 7402, benih bukti 7411; induk tanpa tanda 7499) dibuat dan dilacak sekali di akhir dengan pengaturan terpilih.
* **Jenis bukti**, satu gambar per jenis, dokumen, salinan, dan halaman: `foto` (simulator foto dasar, 1600 px, sudut 0 sampai 30 derajat), `ponsel` (foto yang sama lewat ISP ponsel), `layar` (salinan di monitor simulasi lewat ISP ponsel), `tangkapan` (tangkapan layar 1600 px), `cetak1600` dan `cetak4000` (dicetak printer laser simulasi dengan profil latar bawaan, lalu difoto 1600 atau 4000 px). Induk tanpa tanda lewat `foto`, `cetak1600`, dan `cetak4000`.
* **Kandidat OCR** (dev saja): halaman terektifikasi pada resolusi analisis registrasi dengan `--psm 3`, `4`, atau `6`; gambar bukti dicuplik ulang ke 300 dpi dengan `--psm 3` atau `6`; dan halaman yang dibagi taksiran terang kertas dengan `--psm 3`. Semua `-l ind+eng --oem 1`, satu utas.
* **Aturan pemilihan** (ditetapkan sebelum dev dijalankan): skor = bit benar dikurangi 5 kali bit salah, dijumlahkan atas semua gambar dev. Kandidat dengan skor tertinggi dipilih; bila kandidat lain kurang dari 2 % di bawahnya, dipilih yang total waktu OCR-nya paling kecil di antara kandidat dalam rentang itu.
* **Pelacakan** seperti `make bench`: tanpa registri (seluruh eps), satu tahap. Setiap gambar uji didekode sekali dengan OCR, lalu pengamatan yang sama dituduh dua kali: dengan dan tanpa sub-kanal OCR. Cetakan dua halaman menggabungkan pengamatan halaman 1 dan 2 salinan yang sama pada resolusi yang sama.
* **Ukuran.** Per halaman: bit varian kalimat dan pilihan kata yang tercetak, yang terbaca, yang salah di antara yang terbaca (tanda LLR terhadap kode salinan yang bocor), yang salah dengan yakin (|LLR| paling sedikit 4), dan waktu OCR (Tesseract saja, satu utas). Putusan: benar (tepat salinan yang bocor), tidak cukup bukti (tcb), atau salah (siapa pun selain itu; siapa pun untuk induk tanpa tanda).

Teks OCR tidak pernah keluar dari memori: skrip ini tidak menulis atau mencetaknya, dan hasilnya hanya berisi jumlah, id, dan waktu.

## Menjalankan

```bash
python research/ocr/ukur.py terbit    # penerbitan kedua set dan kedua arm (out/riset_ocr/)
python research/ocr/ukur.py dev       # set dev, semua kandidat; menulis hasil/pilihan.json
python research/ocr/ukur.py uji       # set uji, sekali, dengan DEFAULT_OCR (harus sama dengan pilihan dev)
python research/ocr/ukur.py ringkas   # tabel untuk dokumentasi; menulis hasil/ringkas_uji.json
```

Kolam proses dibatasi 3, BLAS, OpenCV, dan Tesseract satu utas. Penerbitan, gambar bukti, dan pengamatan (larik LLR) ada di `out/riset_ocr/` (besar, tidak di-commit). Baris JSON yang dikutip dokumentasi ada di `hasil/`: `protokol.json`, `terbit.jsonl`, `dev.jsonl`, `pilihan.json`, `uji.jsonl`, `uji_dua_halaman.jsonl`, `ringkas_uji.json`.

## Hasil

Tesseract 5.3.4 (Ubuntu 24.04, `ind.traineddata` sha256 `69786901da87ab87...`, `eng.traineddata` `7d4322bd2a774972...`), satu utas, di mesin uji yang dipakai bersama. Semua gambar sintetis, dua dokumen contoh, satu rahasia kode per dokumen dan set.

**Pemilihan (set dev, 96 gambar, `hasil/pilihan.json`).** Bit tercetak di halaman yang difoto: 780.

| Kandidat | Bit terbaca | Bit salah | Waktu OCR total |
|---|---|---|---|
| psm 3, halaman dibagi terang kertas (`psm3_rata`, terpilih) | 778 | 0 | 299 s |
| psm 6 | 738 | 0 | 296 s |
| psm 6, 300 dpi | 728 | 1 | 478 s |
| psm 4 | 721 | 0 | 298 s |
| psm 3, 300 dpi | 709 | 0 | 470 s |
| psm 3 | 701 | 0 | 290 s |

**Set uji** (dilacak sekali, `hasil/uji.jsonl`, `hasil/uji_dua_halaman.jsonl`, ringkasan `hasil/ringkas_uji.json`). Nota dinas membawa 8 bit terlihat di halaman 1 (2 varian kalimat, 6 pilihan kata) dan 7 di halaman 2 (2 dan 5); surat telegram 9 di halaman 1 (4 dan 5) dan tidak ada di halaman 2.

* **Bit terbaca.** 1.765 dari 1.771 bit yang tercetak di halaman yang ditemukan, 0 salah (0 salah dengan yakin). Foto, foto ISP ponsel, foto monitor, dan tangkapan layar: 810 dari 811 (100 gambar). Foto cetak 1600 px: 475 dari 480; 4000 px: 480 dari 480. Empat kalimat atau titik tidak terbaca (terhapus) dan tiga dibaca dengan keyakinan rendah; tidak ada yang salah.
* **Waktu OCR per halaman** (Tesseract saja): median 2,9 detik, persentil 90 4,6 detik, paling lama 9,8 detik; gambar 1600 px 2,6 sampai 2,7 detik, foto cetak 4000 px 4,3 detik (resolusi efektif median 251 dpi).
* **Putusan.** Benar / tidak cukup bukti / salah. "Tanpa OCR" adalah pengamatan yang sama tanpa sub-kanal OCR; arm `tanpa` adalah penerbitan bawaan tanpa kedua kanal (id salinan, kode, dan bilangan acak cetak dan foto sama).

  | Foto cetak | Dengan OCR | Tanpa OCR | Arm `tanpa` |
  |---|---|---|---|
  | 1600 px, nota hal. 1 | 11 / 9 / 0 | 8 / 12 / 0 | 15 / 5 / 0 |
  | 1600 px, nota hal. 2 | 0 / 20 / 0 | 0 / 20 / 0 | 4 / 16 / 0 |
  | 1600 px, telegram hal. 1 | 4 / 16 / 0 | 1 / 19 / 0 | 12 / 8 / 0 |
  | 4000 px, nota hal. 1 | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 |
  | 4000 px, nota hal. 2 | 0 / 20 / 0 | 0 / 20 / 0 | 16 / 4 / 0 |
  | 4000 px, telegram hal. 1 | 12 / 8 / 0 | 5 / 15 / 0 | 20 / 0 / 0 |
  | 1600 px, nota dua halaman | 20 / 0 / 0 | 18 / 2 / 0 | 20 / 0 / 0 |
  | 1600 px, telegram dua halaman | 6 / 14 / 0 | 3 / 17 / 0 | 14 / 6 / 0 |
  | 4000 px, nota dua halaman | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 |
  | 4000 px, telegram dua halaman | 18 / 2 / 0 | 9 / 11 / 0 | 20 / 0 / 0 |

  Halaman 2 surat telegram (6 baris, tanpa tanda terlihat) tidak pernah cukup sendirian, dan 8 dari 20 fotonya pada 4000 px tidak ditemukan registrasi pada kedua arm. Foto, foto ISP ponsel, foto monitor, dan tangkapan layar: 98 dari 100 benar dengan dan tanpa OCR (pola latar sudah cukup di sana).
* **OCR mengubah 27 putusan** menjadi benar (13 foto satu halaman dan 14 pasangan dua halaman), dan tidak satu pun sebaliknya. Pada 13 foto itu skor salinan yang benar naik dari 0,94 sampai 0,99 kali ambang menjadi 1,01 sampai 1,07 kali.
* **Harga kanal pilihan kata di kertas.** Baris yang memuat titik pilihan kata keluar dari kanal geser: rencana nota dinas membawa 314 posisi geser (penerbitan bawaan 439), surat telegram 200 (249). Pada foto cetak, posisi geser yang terbaca turun dari median 252 menjadi 193 (nota hal. 1), 186 menjadi 121 (nota hal. 2), dan 229 menjadi 180 (telegram hal. 1), sedangkan OCR mengembalikan paling banyak 9 bit per halaman. Karena itu arm `tanpa` lebih sering menyebut salinan yang benar daripada arm `utama` dengan OCR di setiap sel cetak yang hasilnya tidak sama; tiga sel lainnya sama (20 dari 20). OCR memperkecil kerugian itu, tetapi tidak menutupnya.
* **Tuduhan salah: 0** dalam 438 pelacakan gambar dan 160 pasangan dua halaman, masing-masing dengan dan tanpa OCR. Skor tak bersalah tertinggi 0,47 kali ambang. Delapan belas foto induk tanpa tanda (foto dan foto cetak) membaca 144 bit OCR (bentuk dokumen induk) dan tidak menuduh siapa pun (skor tertinggi 0,41 kali ambang).

Batasan: gambar dari simulator, bukan kamera, monitor, atau printer sungguhan; satu versi Tesseract; dua dokumen pendek dengan 7 sampai 9 bit terlihat per halaman, varian dari tabel frasa tiruan, dan leksikon draf tingkat A; satu rahasia kode per dokumen dan set, jadi foto dalam satu sel tidak saling bebas sepenuhnya. Pengaturan OCR dipilih pada set dev, yang juga memakai simulator yang sama.
