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
