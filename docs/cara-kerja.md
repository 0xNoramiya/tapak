# Cara kerja TAPAK

[Kembali ke README](../README.md) · [Operasi](operasi.md) · [Keamanan dan batasan](keamanan.md)

## Lima kanal

Kode penerima yang sama ditanam di empat kanal, ditambah token kanari sebagai kanal kelima. Kanal mana pun boleh rusak; dekoder menggabungkan apa yang tersisa.

| Kanal | Yang ditanam | Kebocoran yang ditangani |
|---|---|---|
| 1. Geser kata dan baris | kelompok kata bergeser horizontal dan baris bergeser vertikal sebesar 0,05 mm. Bit dikodekan relatif terhadap tetangga (kontrol, data, kontrol), sehingga sisa distorsi perspektif saling meniadakan | cetak, foto, tangkapan layar |
| 2. Pola latar | pola acak berfrekuensi rendah +/-2 tingkat abu-abu (sel 2 mm). Setiap posisi kode menempati 8 sel yang tersebar dan didekode secara buta per bit. Profil cetak (opsional): 242 +/- 5 | tangkapan layar, foto layar; dengan profil cetak juga kertas cetak ([di bawah](#salinan-yang-dicetak)) |
| 3. Karakter tak terlihat | sepasang simbol lebar-nol sebelum dan sesudah kata (2 bit per simbol) serta huruf kembar Kiril pada kata huruf kecil | salin-tempel, berkas diteruskan |
| 4. Varian semantik | parafrasa kalimat pembuka, penutup, dan tembusan oleh LLM lokal, disetujui manusia | pengetikan ulang, tetapi hanya beberapa bit (4 pada contoh), belum cukup untuk menyebut nama |
| 5. Kanari DNS | satu subdomain unik per salinan di bawah domain kanari. Pendengar DNS mencatat kapan nama itu dicari dan resolver mana yang bertanya, bukan siapa pembukanya. Token ini tidak membawa kode Tardos | berkas dibuka di luar jaringan satuan, di Adobe Reader atau Word |

## Kode Tardos

Setiap dokumen memiliki vektor bias p (distribusi arcsine dengan batas t = 1/(300c)) dan setiap salinan memiliki kata kode biner x_j. Panjang kode m = K c^2 ln(1/eps1) dengan eps1 = eps/N (batas gabungan untuk N penerima) dan K = 2 pi^2 (bawaan) atau 100 (konservatif). Skor tuduhan memakai skor simetris Skoric dkk.: S_j = jumlah w_i U(y_i, x_ji, p_i).

## Ambang ditetapkan sebelum skor dihitung

Aturan ambang ditetapkan saat penerbitan dan dicatat di registri, bersama ambang Z untuk pembacaan penuh. Untuk setiap bukti, TAPAK menghitung ambang Z setelah dekode, dengan batas Chernoff yang dihitung dari vektor bias dokumen yang sebenarnya dan bobot dekoder. Posisi yang tidak terbaca tidak dihitung, dan setiap posisi memakai bit bocor terburuk. Perhitungan ini tidak melihat kode penerima mana pun. Nilainya dicatat dengan cap waktu di hasil dan berita acara, baru kemudian skor dihitung.

Jaminan tuduhan salah karenanya tidak bergantung pada konstanta K maupun pendekatan Gauss. K hanya memengaruhi tingkat deteksi, dan itu diukur dengan simulasi.

Satu kebocoran dapat dilacak berulang kali, misalnya dengan potongan atau gabungan bukti yang berbeda. Karena itu setiap pelacakan dokumen yang tercatat lebih dulu ditulis di registri dengan nomor urut k per dokumen, sebelum bukti dibaca. Pelacakan ke-k memakai eps_k = eps x 6 / (pi^2 k^2) dan eps1 = eps_k / N, untuk ambang gabungan maupun ambang tiap kanal. Jumlah 1/k^2 untuk semua k adalah pi^2/6, jadi jumlah semua eps_k tepat eps: batas tuduhan salah berlaku untuk semua pelacakan dokumen bersama, selama bukti tiap pelacakan tidak dipilih berdasarkan skor pelacakan sebelumnya ([batasan 13](keamanan.md#batasan)). Peluang tuduhan salah per salinan juga dibagi dengan 6 / (pi^2 k^2). Pelacakan yang tidak tercatat (mode lepas, atau dokumen yang diterbitkan tanpa registri) memakai seluruh eps dan hasilnya menyatakannya.

## Fusi bukti

Setiap kanal menghasilkan rasio log-kemungkinan (LLR) per posisi kode tanpa pernah melihat kode penerima. LLR dijumlahkan; keputusan y_i = tanda LLR, bobot w_i = tanh(|LLR|/2). Skor tuduhan dihitung pada hasil fusi dan pada setiap kanal fisik secara terpisah, sehingga laporan menyebut berapa kanal yang sepakat secara independen. Kanal yang saling bertentangan dilaporkan sebagai kemungkinan manipulasi.

## Aturan keluaran

Nama hanya muncul bersama skor, ambang, dan peluang tuduhan salahnya. Bila tidak ada salinan yang melewati ambang, keluarannya "tidak cukup bukti" dan tidak ada nama yang disebut.

## Arsitektur

```
            +---------------- Terbitkan -----------------+          +------------------ Lacak -------------------+
 PDF induk  |  layout   rencana penandaan (kunci)        |  salinan | foto / tangkapan layar / PDF / DOCX / teks |
 + penerima |  model -> geser, latar, teks, semantik,    |--------->|  rectify (kontur, SIFT, Tesseract) + ECC   |
            |           kanari -> render ulang + gerbang |          |  ch_shift  ch_background  ch_zerowidth     |
            |           visual -> 20 salinan PDF         |          |  ch_semantic  ch_docx                      |
            +----------------------+---------------------+          |        -> fuse (LLR) -> accuse (Chernoff)  |
                                   |                                |        -> berita acara (WeasyPrint)        |
                                   v                                +---------------------+----------------------+
           registri SQLite tambah-saja: rantai SHA-256, tanda tangan Ed25519,             |
           akar Merkle harian; hanya hash, id, dan komitmen kode   <----------------------+  verifikasi silang
                                   ^
                                   |  peristiwa kanari (rantai hash sendiri)
                       pendengar DNS otoritatif (dnslib)
```

```
tapak/
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), attacks, simulate
  marker/       layout, master (font), plan, pdf_shift, background, pdf_zerowidth, semantic, canary,
                docx_marker, render (gambar ulang + gerbang visual), issue (paralel)
  decoder/      rectify, lines (Tesseract), ch_shift, ch_background, ch_zerowidth, ch_semantic, ch_docx,
                image, fuse, accuse, trace, report (berita acara)
  registry/     chain (rantai hash, trigger tambah-saja), signing (Ed25519), verify, merkle
  canary_dns/   server (dnslib), store (log berantai)
  llm/          provider (antarmuka), mock (deterministik), llamacpp (lokal, loopback saja)
  learned_wm/   kerangka tanda air berbasis model (opsional, belum dilatih)
  web/          FastAPI + HTMX, antarmuka berbahasa Indonesia
  photos.py     simulator foto, tangkapan layar, dan printer
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
scripts/        alat ukur dan eksperimen (scripts/cetak: pengukuran salinan cetak)
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
docs/           dokumentasi, gambar README (docs/figures membuatnya ulang), keluaran simulasi dan benchmark
```

## Angka simulasi

Perintah: `tapak simulate --n 100 --c 3 --eps 1e-6 --trials 1000` (m = 3273 bit). Simulasi ini bekerja di tingkat kode: koalisi langsung menyerang bit kode, tanpa dokumen, gambar, atau derau kanal.

| Strategi kolusi | Tuduhan salah | Deteksi (minimal 1 anggota) | Semua anggota tertangkap | Z rata-rata | Skor koalisi tertinggi |
|---|---|---|---|---|---|
| mayoritas | 0 / 1.000 | 100 % | 100 % | 372,5 | 772,6 |
| minoritas | 0 / 1.000 | 100 % | 100 % | 372,5 | 768,1 |
| campuran acak | 0 / 1.000 | 100 % | 100 % | 372,5 | 773,3 |
| lempar koin | 0 / 1.000 | 100 % | 100 % | 372,5 | 769,7 |
| selalu 1 | 0 / 1.000 | 100 % | 100 % | 372,5 | 770,9 |
| selalu 0 | 0 / 1.000 | 100 % | 100 % | 372,5 | 770,6 |
| hapus (rata-rata dua salinan) | 0 / 1.000 | 100 % | 100 % | 306,5 | 722,8 |

Skor tertinggi penerima tak bersalah di seluruh percobaan adalah 72 % dari ambang. Nol tuduhan salah dalam 1.000 percobaan hanya menunjukkan bahwa lajunya kira-kira di bawah 3 x 10^-3, jadi batasnya juga diuji pada tingkat yang dapat diukur. Pada target 10^-2 laju empirisnya 6,8 x 10^-4, dan pada target 10^-3 lajunya 3,3 x 10^-5 (dari 582.000 skor penerima tak bersalah). Hasil ini konsisten dengan batas Chernoff yang konservatif. Pada 10^-6 batasnya tidak dapat diuji dengan sampling; jaminannya berasal dari batas matematis.

Uji tambahan (berkas lengkap di [`results/`](results/)):

| Skenario | Tuduhan salah | Deteksi | Semua tertangkap |
|---|---|---|---|
| N=20, c=3 (m=2987) | 0 | 100 % | 100 % |
| N=100, c=3, kanal berderau: 5 % bit salah, 35 % terhapus | 0 | 100 % | 98 sampai 100 % |
| N=100, kode untuk c=3 diserang 5 orang (di luar rancangan), 300 percobaan | 0 | 100 % | 42 sampai 49 % (strategi hapus: 100 %) |

Tabel parameter (eps = 10^-6, `tapak simulate --table`):

| N | c | eps1 | m (K=2 pi^2) | m (K=100) | Z Chernoff | Z Gauss | rata-rata skor kolusi per anggota |
|---|---|---|---|---|---|---|---|
| 20 | 2 / 3 / 5 | 5e-8 | 1328 / 2987 / 8297 | 6725 / 15131 / 42029 | 233 / 340 / 552 | 194 / 291 / 485 | 423 / 634 / 1056 |
| 50 | 2 / 3 / 5 | 2e-8 | 1400 / 3150 / 8749 | 7092 / 15955 / 44319 | 246 / 359 / 582 | 205 / 308 / 514 | 446 / 668 / 1114 |
| 100 | 2 / 3 / 5 | 1e-8 | 1455 / 3273 / 9091 | 7369 / 16579 / 46052 | 256 / 373 / 605 | 214 / 321 / 535 | 463 / 695 / 1158 |
| 500 | 2 / 3 / 5 | 2e-9 | 1582 / 3559 / 9885 | 8013 / 18028 / 50076 | 278 / 405 / 658 | 234 / 351 / 585 | 504 / 755 / 1259 |

## Hasil lain

| Pengujian | Hasil |
|---|---|
| Kumpulan foto sintetis (`make photos` lalu `make bench`): 32 foto layar bersudut 0 sampai 30 derajat dan 8 tangkapan layar dari 4 salinan (halaman 1), dikompresi JPEG dua kali seperti WhatsApp | 37 dari 40 benar, 3 "tidak cukup bukti" (foto terlalu terang), 0 tuduhan salah |
| Foto kertas cetak (`make photos-cetak` lalu `make bench`, dilaporkan terpisah): halaman 1 dan 2 dari 4 salinan yang sama, dicetak printer laser simulasi dengan profil latar bawaan, 16 foto (10 dan 30 derajat, 1600 px) dan 8 pasangan dua halaman | satu halaman 2 dari 16 benar (keduanya halaman 1 salinan #20), dua halaman 3 dari 8, 0 tuduhan salah |
| 10 foto sintetis bersudut sampai 30 derajat | 10 dari 10 benar |
| Halaman gabungan digital: setengah atas salinan A, setengah bawah salinan B (2 pasangan) | penerima A dan B dituduh, tidak ada orang lain |
| Teks salinan disalin-tempel (MuPDF dan poppler) | kode utuh, salinan teridentifikasi |
| Teks diketik ulang dengan 5 % salah ketik (kanal semantik) | 4 bit semantik pulih 20 dari 20 percobaan; tidak cukup untuk menyebut nama |
| Penerbitan 20 salinan dokumen 2 halaman | sekitar 4 sampai 5 detik |
| Kanari DNS, pembukaan disimulasikan (kueri langsung ke pendengar lokal) | tercatat dalam sekitar 0,1 detik (syarat: di bawah 5 detik) |
| Registri: verifikasi hanya dengan kunci publik, setiap perubahan baris terdeteksi | lulus |
| `make demo` (skenario lengkap) | sekitar 15 detik |

## Salinan yang dicetak

Pola latar bawaan (253 +/- 2) terlalu terang untuk printer: printer menggambar tingkat abu-abu di atas sekitar 250 sebagai kertas polos. Foto salinan yang dicetak karena itu hanya membawa kanal geser, sekitar 80 sampai 100 posisi kode terbaca per halaman. Printer sungguhan belum diuji; angka di bagian ini berasal dari simulator printer dan foto sintetis. Hasil lengkapnya ada di [`results/`](results/) (`cetak_summary.json`, `cetak_visibility.json`, `cetak_calibration.json`, `cetak_needbits.txt`), dan cara membuatnya ulang di [operasi](operasi.md#mengukur-salinan-yang-dicetak).

### Simulator printer

`print_page` di `tapak/photos.py` meniru printer laser kantor 600 dpi (preset `INKJET` untuk inkjet). Lembar hasilnya lalu difoto oleh simulator foto yang sama dengan benchmark.

1. Teks dirasterisasi di kisi printer tanpa anti-aliasing, seperti RIP printer.
2. Tingkat abu-abu 250 ke atas menjadi kertas polos.
3. Warna lain diraster dengan raster AM 106 lpi pada 45 derajat.
4. Banding drum dan roda gigi menggeser garis pindai sampai 25 um.
5. Sebaran sinar laser dan toner, derau toner, dan ambang pengembangan membuat tepi huruf melebar sekitar 22 um dan bergerigi sekitar 15 um.
6. Kertas miring sampai 0,25 derajat, bergeser sampai 1 mm, dan skalanya meleset sampai 0,2 %.
7. Cahaya menyebar di dalam kertas (dot gain optis), dan kertas punya tekstur serat serta awan.

Nilainya dari literatur dan perkiraan orde besaran, bukan dari printer yang diukur. Kalibrasinya (`scripts/cetak/calibrate.py`): abu-abu 50 % tercetak 11,7 poin persentase lebih gelap, dan tingkat 245 sampai 249 tercetak sebagai titik terkecil (dL* -1,9). Yang tidak dimodelkan: koreksi nada driver, mode hemat toner, printer warna, mesin fotokopi dan pemindai, serta pemrosesan gambar di kamera ponsel.

### Templat induk tepat

Dekoder geser mencocokkan setiap kelompok kata pada foto dengan templat dari dokumen induk. MuPDF menggambar glif kecil dari cache bitmap pada piksel utuh, jadi templat lama (render 4 kali lebih rapat lalu dirata-rata) menggeser kelompok kata sampai puluhan mikrometer, sama untuk setiap salinan dan foto. Templat tepat dirender pada 3.200 dpi atau lebih, saat glif digambar sebagai kurva tanpa pembulatan, per pita, lalu dirata-rata turun. Render tepat induk pada 4.800 dpi bergeser kurang dari 0,3 um terhadap templat ini untuk setiap kelompok. Rendernya memerlukan sekitar 4 sampai 13 detik per halaman di mesin uji yang dipakai bersama, sekali untuk setiap halaman dan resolusi analisis (lalu disimpan di cache).

Pada foto kertas cetak, templat tepat hampir tidak mengubah hasil (tabel di bawah, dibandingkan dengan templat lama pada foto yang sama). Pada benchmark README putusannya identik untuk ke-64 pelacakan.

### Hasil dengan profil latar bawaan

Protokol: printer laser simulasi, foto sintetis (sudut pandang diundi 0 sampai 30 derajat, parameter lain diundi), salinan 1 sampai 20 dari 100 (N = 100, c = 3, eps = 10^-6), dekoder produksi. "Dua halaman" menggabungkan foto halaman 1 dan 2 salinan yang sama dalam satu pelacakan.

| | 1600 px (WhatsApp standar) | 4000 px (WhatsApp HD) |
|---|---|---|
| Posisi geser terbaca per halaman (hal. 1 / hal. 2) | 102 / 79 | 103 / 80 |
| Galat bit kanal geser (hal. 1 / hal. 2) | 4,8 % / 3,3 % | 0 % / 0 % |
| Pola latar ditemukan | 0 dari 40 | 0 dari 40 |
| Satu halaman menyebut salinan yang benar | 0 dari 40 | 0 dari 40 |
| Skor salinan yang benar, median (maks.), persen ambang | 59 % (79 %) | 62 % (85 %) |
| Dua halaman menyebut salinan yang benar | 5 dari 20 | 8 dari 20 |
| Tuduhan salah | 0 | 0 |
| Templat lama, foto yang sama: galat bit; dua halaman | 4,6 % / 3,1 %; 4 dari 20 | 0,05 % / 0,19 %; 8 dari 20 |

Salinan yang benar selalu berskor tertinggi, tetapi satu halaman tidak mencapai ambang, bahkan pada 4000 px ketika semua bit yang terbaca benar. Batasnya kapasitas, bukan derau: menurut simulasi tingkat kode dengan vektor bias dokumen ini (`scripts/cetak/needbits.py`), satu pembocor perlu sekitar 300 posisi terbaca (galat sampai 5 %), dan menyebut minimal satu dari tiga anggota koalisi perlu 1.200 sampai 1.500.

### Profil latar cetak (opsional)

`tapak issue ... --latar cetak` menggambar pola latar 242 +/- 5 (tingkat 237 sampai 247), di bawah ambang printer. Dekodernya sama, dan catatan penerbitan menyimpan pengaturan pola. Dengan protokol yang sama (100 salinan diterbitkan dengan profil ini):

| | 1600 px | 4000 px |
|---|---|---|
| Pola latar ditemukan | 40 dari 40 | 40 dari 40 |
| Galat bit kanal latar (hal. 1 / hal. 2); median per foto | 1,7 % / 1,8 %; 0,5 % / 0,4 % | 3,1 % / 1,4 %; 0,4 % / 0,3 % |
| Satu halaman menyebut salinan yang benar | 40 dari 40 | 40 dari 40 |
| Skor salinan yang benar, median (min.), kali ambang | 4,3 (2,6) | 4,3 (2,5) |
| Dua halaman menyebut salinan yang benar | 20 dari 20 | 20 dari 20 |
| Tuduhan salah; skor tak bersalah tertinggi | 0; 65 % ambang | 0; 58 % ambang |

* **Kolusi c = 3 di kertas.** Tiga salinan dipotong menjadi pita atas, tengah, dan bawah di ruang kosong antarbaris, disatukan dalam satu lembar, dicetak, lalu difoto (16 koalisi dari salinan 1 sampai 20, 1600 px). Satu halaman menyebut minimal satu anggota pada 32 dari 32 halaman dan ketiganya pada 27 dari 32. Dua halaman: 16 dari 16 dan 15 dari 16. Tidak ada orang tak bersalah yang disebut (skor tertinggi 49 % ambang).
* **Printer inkjet simulasi** (halaman 1 salinan 1 sampai 10, 1600 px): 10 dari 10, galat bit 0,8 %.
* **Foto yang terlalu terang** tetap melemahkan pola: tiga foto terburuk (35 sampai 45 % piksel jenuh) bergalat bit 21 sampai 27 %, tetapi masih menyebut salinan yang benar.

Harganya tampilan. Seluruh halaman tampak abu-abu muda: dL* -3,4 terhadap kertas pada laser simulasi dan -4,5 di layar. Teksturnya di ambang terlihat: S-CIELAB pada 35 cm rata-rata 1,1 dan persentil 95 sebesar 3,5 (pola layar bawaan: 0,4 dan 0,8; raster abu-abu polos setingkat: 0,75 dan 2,0), dengan 1 sebagai beda yang nyaris terlihat (`scripts/cetak/visibility.py`). Karena itu profil ini tidak menjadi bawaan dan TAPAK menampilkan peringatan saat dipakai. Printer biasanya menyisakan tepi putih beberapa milimeter, sehingga halaman abu-abu tampak berbingkai putih. Belum diuji dengan printer, ponsel, maupun pengamat sungguhan.

## Keputusan desain yang menyimpang dari spesifikasi awal

| Spesifikasi | Yang dibangun | Alasan |
|---|---|---|
| Kode penuh ditanam di setiap kanal | kanal teks membawa seluruh m bit; setiap halaman membawa irisannya sendiri di kanal fisik; tuduhan hanya dihitung atas posisi yang terbaca dengan ambang ketat untuk himpunan itu | c=3, eps=10^-6 memerlukan sekitar 3000 bit, sedangkan geser kata dan baris hanya memuat sekitar 90 bit per halaman. Skala c^2 ln(1/eps) adalah batas bawah untuk kode tahan kolusi apa pun |
| Geser 0,01 sampai 0,03 mm | 0,05 mm (dapat diatur, maksimum 0,05 mm) | 0,01 sampai 0,03 mm hanya 0,1 sampai 0,3 piksel pada foto ponsel satu halaman A4; tidak terukur setelah JPEG |
| "Selisih piksel tak terlihat" | didefinisikan secara geometris: di antara dua salinan mana pun, tidak ada glif yang bergeser lebih dari 0,1 mm per sumbu (1 menit busur pada jarak baca 35 cm). Diuji pada 600 dpi: perbedaan piksel hanya ada di kotak kata yang digeser (di luar itu hanya pola latar, maksimum 4 tingkat abu-abu) dan pusat tinta bergeser sesuai rencana | tanda geometris mengubah posisi tepi, bukan kontras; ambang tingkat abu-abu tidak bermakna untuk itu |
| Pola latar didekode dengan korelasi terhadap kandidat | korelasi buta per bit (spread spectrum) | korelasi terhadap kandidat memakai kode penerima dan merusak jaminan tuduhan salah Tardos |
| Registri menyimpan kode | registri menyimpan komitmen (`code_digest`); kode diturunkan ulang dari rahasia kode | siapa pun yang dapat membaca kode dapat memfitnah penerima |
| Kanari DOCX lewat referensi font eksternal | relasi gambar eksternal | Word tidak mengambil font eksternal |
| Banyak simbol lebar-nol di akhir kata | paling banyak dua simbol per posisi (sebelum dan sesudah kata), dari alfabet berbeda | MuPDF dan poppler membuang glif identik yang ditumpuk di posisi yang sama (dianggap tebal palsu) |
| Ambang Z ditetapkan sebelum analisis | aturan ambang ditetapkan saat penerbitan; nilai Z dihitung setelah dekode dari posisi yang benar-benar terbaca, sebelum skor dihitung | kanal yang rusak menghapus posisi; ambang tetap untuk pembacaan penuh akan terlalu ketat untuk bukti parsial. Aturannya tetap dan tidak pernah melihat kode penerima, sehingga tidak dapat disesuaikan setelah melihat hasil |
| Konstanta "Skoric 2006, 2 pi^2" | dipertahankan sebagai bawaan, atribusi dikoreksi | 2 pi^2 berasal dari Skoric, Vladimirova, Celik, dan Talstra untuk skor asimetris (pendekatan Gauss). Dengan skor simetris konstanta asimtotiknya pi^2/2, jadi ada margin sekitar 4 kali. Untuk c kecil ini bukan batas yang terbukti, tetapi jaminan tuduhan salah TAPAK tetap ketat karena berasal dari ambang Chernoff |

## Referensi

1. G. Tardos. Optimal probabilistic fingerprint codes. Proc. 35th ACM STOC, 2003, hlm. 116-125. Versi jurnal: J. ACM 55(2), 2008.
2. B. Skoric, T. U. Vladimirova, M. Celik, J. C. Talstra. Tardos fingerprinting is better than we thought. IEEE Trans. Inf. Theory 54(8):3663-3676, 2008. arXiv:cs/0607131.
3. B. Skoric, S. Katzenbeisser, M. U. Celik. Symmetric Tardos fingerprinting codes for arbitrary alphabet sizes. Des. Codes Cryptogr. 46(2):137-166, 2008. IACR ePrint 2007/041.
4. T. Laarhoven, B. de Weger. Optimal symmetric Tardos traitor tracing schemes. Des. Codes Cryptogr. 71(1):83-103, 2014. arXiv:1107.3441.
5. J. T. Brassil, S. Low, N. F. Maxemchuk. Copyright protection for the electronic distribution of text documents. Proc. IEEE 87(7), 1999 (pergeseran baris dan kata).
6. M. Tancik, B. Mildenhall, R. Ng. StegaStamp: Invisible hyperlinks in physical photographs. CVPR 2020.
