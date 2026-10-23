# Cara kerja TAPAK

[Kembali ke README](../README.md) · [Operasi](operasi.md) · [Keamanan dan batasan](keamanan.md)

## Lima kanal, ditambah satu kanal pilihan

Kode penerima yang sama ditanam di empat kanal, ditambah token kanari sebagai kanal kelima. Kanal keenam, pilihan kata, hanya dipakai bila penerbit memilihnya dan meninjau setiap titiknya ([rinciannya di bawah](#kanal-pilihan-kata-opsional)). Kanal mana pun boleh rusak; dekoder menggabungkan apa yang tersisa.

| Kanal | Yang ditanam | Kebocoran yang ditangani |
|---|---|---|
| 1. Geser kata dan baris | kelompok kata bergeser horizontal dan baris bergeser vertikal. Skema v2 (bawaan sejak penerbitan ini): setiap kelompok kata bergeser 0,025 mm dan satu baris dibaca bersama setelah pergeseran dan kemiringannya diproyeksikan keluar ([rincian](#skema-geser-v2)). Skema v1 (semua dokumen lama): kelompok data di antara dua kelompok kontrol bergeser 0,05 mm dan dibaca relatif terhadap tetangganya. Baris berselang-seling 0,05 mm pada keduanya | cetak, foto, tangkapan layar |
| 2. Pola latar | pola acak berfrekuensi rendah +/-2 tingkat abu-abu (sel 2 mm). Setiap posisi kode menempati 8 sel yang tersebar dan didekode secara buta per bit. Profil cetak (opsional): 242 +/- 5 | tangkapan layar, foto layar; dengan profil cetak juga kertas cetak (printer simulasi, [di bawah](#salinan-yang-dicetak)) |
| 3. Karakter tak terlihat | sepasang simbol lebar-nol sebelum dan sesudah kata (2 bit per simbol) serta huruf kembar Kiril pada kata huruf kecil | salin-tempel, berkas diteruskan |
| 4. Varian semantik | parafrasa kalimat pembuka, penutup, dan tembusan oleh LLM lokal, disetujui manusia | pengetikan ulang, tetapi hanya beberapa bit (4 pada contoh), belum cukup untuk menyebut nama. Juga dibaca dengan OCR dari foto, tangkapan layar, dan cetakan ([di bawah](#teks-terlihat-pada-bukti-gambar-ocr)) |
| 5. Kanari DNS | satu subdomain unik per salinan di bawah domain kanari. Pendengar DNS mencatat kapan nama itu dicari dan resolver mana yang bertanya, bukan siapa pembukanya. Token ini tidak membawa kode Tardos | berkas dibuka di luar jaringan satuan, di Adobe Reader atau Word |
| 6. Pilihan kata (opsional) | bentuk bermakna sama dari tabel leksikon draf, misalnya "terdiri atas" atau "terdiri dari", "dan" atau "serta". Setiap titik disetujui manusia | pengetikan ulang oleh satu pembocor, bila dokumennya cukup panjang (terukur: mulai sekitar 1.300 kata isi; TAPAK menyatakan cukup mulai 64 bit, sekitar 1.800 kata isi); tidak tahan kolusi. Bentuknya terlihat di kertas, jadi dapat ditiru, dan dibaca dengan OCR dari foto, tangkapan layar, dan cetakan |

## Dokumen induk hasil pindai

Halaman hasil pindai tidak memiliki lapisan teks untuk digambar ulang, jadi tandanya dibuat langsung di piksel gambar halaman (`tapak/marker/raster.py`). Rencana penandaan, posisi kode, kunci, dan kode Tardos sama dengan halaman teks.

* **Deteksi per halaman.** Halaman dianggap hasil pindai bila isi yang terlihat hanya satu gambar yang menutupi hampir seluruh halaman. Teks di atasnya boleh tidak ada atau tak terlihat (lapisan OCR, mode render 3). Halaman lain tetap memakai jalur teks, jadi dokumen campuran ditangani per halaman.
* **Kotak kata.** Tesseract (bahasa `ind`, mesin LSTM, satu utas, resolusi dinyatakan) membaca gambar halaman induk satu kali. Kotak kata dan barisnya menjadi baris, kata, dan kelompok geser seperti pada halaman teks. Catatan penerbitan dan registri hanya menyimpan hash daftar kotak itu dan versi Tesseract, tanpa kotak, kata, atau gambar.
* **Geser.** Tinta kelompok yang membawa bit bergeser sebesar geser skemanya (skema v1: kelompok data 0,05 mm, 0,59 piksel pada 300 dpi; skema v2: setiap kelompok kotak kata 0,025 mm) dengan interpolasi kubik subpiksel, lalu dicampur lewat masker lunak yang hanya mencakup tinta dan 2 piksel di sekitarnya. Tekstur kertas di sekitar kata tidak ikut diinterpolasi, sehingga tidak ada tepi petak atau lingkaran cahaya. Piksel yang ditinggalkan tinta mengambil kertas di sebelahnya dari gambar induk. Baris data bergeser vertikal dengan cara yang sama.
* **Pola latar.** Pola berkunci +/-2 tingkat abu-abu ditambahkan hanya ke piksel kertas, yaitu piksel yang paling banyak 20 tingkat lebih gelap dari warna kertas halaman itu, pada resolusi gambar halaman. Dekoder memakai batas yang sama untuk menyisihkan tinta.
* **Kanal lain.** Kanari tetap dipasang karena berupa aksi PDF. Karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di halaman pindaian, dan rencana penandaan menyatakannya.
* **Salinan.** Gambar halaman bertanda menggantikan gambar induk sebagai Flate tanpa kehilangan data, dengan ukuran dan letak yang sama. Lapisan OCR tak terlihat dari induk tidak ikut ke salinan, karena berisi kata dokumen induk tanpa tanda.
* **Gerbang.** Salinan tanpa tanda harus identik piksel demi piksel dengan gambar halaman induk, dan halamannya juga dirender sama dengan halaman induk (pada lebih dari separuh resolusi pindai). Setiap salinan bertanda hanya boleh berubah di sekitar tinta yang digeser dan, di kertas, sebesar pola latar (-4 sampai +2 tingkat). Bila tidak, penerbitan berhenti.
* **Pelacakan.** Templat dekoder adalah gambar halaman induk itu sendiri. Kotak kata dibaca ulang dengan panggilan Tesseract yang sama dan hanya dipakai bila hash-nya sama dengan catatan penerbitan. Bila berbeda, misalnya karena versi Tesseract lain, kanal geser halaman pindaian ditolak dengan catatan, dan pola latar tetap dibaca. Slot geser halaman pindaian ditempatkan setelah semua halaman teks, sehingga perubahan kotak kata tidak pernah menggeser posisi kode halaman teks. Ambang dan aturan tuduhan tidak berubah.

Angka terukurnya ada di [batasan 8](keamanan.md#batasan).

## Kode Tardos

Setiap dokumen memiliki vektor bias p (distribusi arcsine dengan batas t = 1/(300c)) dan setiap salinan memiliki kata kode biner x_j. Panjang kode m = K c^2 ln(1/eps1) dengan eps1 = eps/N (batas gabungan untuk N penerima) dan K = 2 pi^2 (bawaan) atau 100 (konservatif). Skor tuduhan memakai skor simetris Skoric dkk.: S_j = jumlah w_i U(y_i, x_ji, p_i).

## Ambang ditetapkan sebelum skor dihitung

Aturan ambang ditetapkan saat penerbitan dan dicatat di registri, bersama ambang Z untuk pembacaan penuh. Untuk setiap bukti, TAPAK menghitung ambang Z setelah dekode, dengan batas Chernoff yang dihitung dari vektor bias dokumen yang sebenarnya dan bobot dekoder. Posisi yang tidak terbaca tidak dihitung, dan setiap posisi memakai bit bocor terburuk. Perhitungan ini tidak melihat kode penerima mana pun (tahap lanjutan [pelacakan bertahap](#pelacakan-bertahap) memakai kode salinan yang sudah dituduh, tetapi tidak pernah kode salinan yang sedang dinilai). Nilainya dicatat dengan cap waktu di hasil dan berita acara, baru kemudian skor dihitung.

Jaminan tuduhan salah karenanya tidak bergantung pada konstanta K maupun pendekatan Gauss. K hanya memengaruhi deteksi. Peluang koalisi lolos juga dibatasi secara matematis, untuk pembacaan penuh dan juga untuk bit salah dan bobot lunak dekoder, selama derau kanal tidak bergantung pada kode ([batas deteksi terbukti](#batas-deteksi-terbukti)). Penghapusan yang sengaja menyasar posisi tempat salinan koalisi sama tidak tercakup; pada salinan sungguhan koalisi seperti itu lolos. Dekoder memberi peringatan bila polanya terlihat, dan juga bila bacaan yang jelas tidak menyebut siapa pun, tetapi koalisi yang tahu kedua pemeriksaan itu tetap dapat lolos ([koalisi yang memahami TAPAK](#koalisi-yang-memahami-tapak)).

Satu kebocoran dapat dilacak berulang kali, misalnya dengan potongan atau gabungan bukti yang berbeda. Karena itu setiap pelacakan dokumen yang tercatat lebih dulu ditulis di registri dengan nomor urut k per dokumen, sebelum bukti dibaca. Pelacakan ke-k memakai eps_k = eps x 6 / (pi^2 k^2) dan eps1 = eps_k / N, untuk ambang gabungan maupun ambang tiap kanal. Jumlah 1/k^2 untuk semua k adalah pi^2/6, jadi jumlah semua eps_k tepat eps: batas tuduhan salah berlaku untuk semua pelacakan dokumen bersama, selama bukti tiap pelacakan tidak dipilih berdasarkan skor pelacakan sebelumnya ([batasan 13](keamanan.md#batasan)). Peluang tuduhan salah per salinan juga dibagi dengan 6 / (pi^2 k^2). Pelacakan yang tidak tercatat (mode lepas, atau dokumen yang diterbitkan tanpa registri) memakai seluruh eps dan hasilnya menyatakannya. Di dalam satu pelacakan, jatah eps_k dibagi lagi antartahap [pelacakan bertahap](#pelacakan-bertahap).

## Fusi bukti

Setiap kanal menghasilkan rasio log-kemungkinan (LLR) per posisi kode tanpa pernah melihat kode penerima. LLR dijumlahkan; keputusan y_i = tanda LLR, bobot w_i = tanh(|LLR|/2). Skor tuduhan dihitung pada hasil fusi dan pada setiap kanal fisik secara terpisah, sehingga laporan menyebut berapa kanal yang sepakat secara independen. Kanal yang saling bertentangan dilaporkan sebagai kemungkinan manipulasi.

**Satu slot yang terbaca lebih dari sekali.** Bila beberapa berkas bukti dari satu kebocoran memperlihatkan slot yang sama, setiap pembacaan ikut dijumlahkan: dua foto halaman yang sama menjumlahkan LLR geser dan latarnya (derau kameranya bebas, cetakannya tidak), dan PDF yang diteruskan bersama fotonya menambahkan pembacaan PDF yang persis ke pembacaan foto. Pengecualiannya kanal yang tandanya kata terlihat, yaitu varian kalimat dan pilihan kata. Frasa tercetak yang sama, dibaca dari lapisan teks PDF, teks tempelan, atau teks OCR sebuah gambar ([di bawah](#teks-terlihat-pada-bukti-gambar-ocr)), adalah satu tanda, bukan dua bukti yang saling bebas: galat OCR berulang pada cetakan yang sama, dan lapisan teks serta OCR halaman yang sama sepakat dengan sendirinya. Karena itu pembacaan satu posisi dari berkas yang berbeda digabung sebagai jumlahnya, dipangkas ke |LLR| tunggal terbesar (`fuse.combine_repeated_reads`). Pembacaan yang sepakat memberi keyakinan pembacaan terbaik saja, tidak lebih; pembacaan yang bertentangan menurunkannya, sampai terhapus bila sama kuat. Satu berkas bukti memberi LLR yang persis sama dengan sebelumnya, dan aturan ini hanya memakai LLR, tidak pernah kode penerima. Kanal sepakat dihitung per kanal fisik, jadi varian kalimat yang dibaca dari teks dan dari OCR tetap satu kanal ("semantik"), bukan dua.

## Pelacakan bertahap

Koalisi yang lebih besar dari c biasanya hanya tertangkap sebagian oleh tuduhan biasa. Pelacakan bertahap mencari anggota lainnya dengan bantuan salinan yang sudah dituduh. Turunan lengkap dan buktinya ada di docstring `tapak/tardos/staged.py`.

* **Tahap 1** adalah tuduhan biasa di atas.
* **Tahap 2.** Bila tahap 1 menuduh salinan, setiap salinan lain dinilai ulang dengan bobot baru. Posisi yang bit bocornya tidak dimiliki satu pun salinan yang sudah dituduh disebut posisi tak terjelaskan. Menurut asumsi penandaan, di posisi itu sedikitnya satu anggota koalisi lain memegang bit bocor, jadi hanya posisi itu yang diberi bobot. Di posisi lain, isi salinan anggota yang tersisa bergantung pada strategi koalisi (mayoritas atau minoritas), jadi bobotnya nol.
* **Besar bobot** diturunkan dari sumbangan skor yang diharapkan dari anggota yang belum dituduh, dengan model acuan dua anggota tersisa, lalu dipadankan dengan ambang Chernoff: sqrt(q(1-q)) ln(1/q) bila bit bocor adalah simbol yang lebih jarang (q = min(p, 1-p)), jauh lebih kecil bila bit bocor adalah simbol yang umum. Bobot terbesar jatuh pada q sekitar 0,1. Model acuan ditetapkan sebelum simulasi dan hanya memengaruhi deteksi. Bobot dekoder ikut dikalikan.
* **Tahap 3 dan 4** mengulang langkah yang sama dengan semua salinan yang sudah dituduh. Pelacakan berhenti pada tahap pertama yang tidak menuduh siapa pun. Salinan yang sudah dituduh tidak dinilai lagi.
* **Ambang.** Setiap tahap memakai ambang Chernoff yang sama dengan bobot tahapnya dan jatah eps-nya sendiri. Ambang itu dicatat dengan cap waktu sebelum skor tahap tersebut dihitung.

**Jaminan tuduhan salah.** Bobot dan ambang tahap lanjutan memakai kata kode salinan yang sudah dituduh, dan itu kode penerima. Keduanya tidak pernah memakai kata kode salinan yang sedang dinilai. Untuk salinan tak bersalah j yang belum dituduh, himpunan salinan yang sudah dituduh sama dengan hasil prosedur yang sama tanpa salinan j, jadi tidak bergantung pada kode j. Batas Chernoff tahap itu lalu berlaku persis seperti pada tahap 1. Peluang j dituduh pada tahap mana pun paling besar jumlah eps1 semua tahap, dan jumlah itu sama dengan jatah pelacakan dibagi n_max. Bukti ini tidak mengandaikan salinan yang sudah dituduh benar anggota koalisi.

**Anggaran.** Kebijakan `bertahap-v1` memberi tahap 1 90 % jatah pelacakan. Tahap 2, 3, dan 4 membagi 10 % sisanya dengan perbandingan 1 : 1/4 : 1/9, yaitu 7,3 %, 1,8 %, dan 0,8 % jatah pelacakan. Kebijakan dan eps setiap tahap ditulis di entri `trace` registri bersama nomor pelacakan, sebelum bukti dibaca. Pelacakan lewat `--doc` dan halaman Lacak selalu bertahap. Entri `trace` lama tanpa kolom ini tetap lulus verifikasi dan diulang dengan satu tahap. Di mode lepas, `--bertahap` mengulang pelacakan bertahap seperti tercatat di berita acara; tanpa itu mode lepas tetap satu tahap. Peluang tuduhan salah per salinan dibagi jatah tahap yang menuduhnya.

**Harga untuk tahap 1.** Ambang tahap 1 naik sekitar 0,3 %: untuk N = 20 dan c = 3, dari 345,4 menjadi 346,5 pada pelacakan pertama. Batas terbukti peluang koalisi lolos naik sekitar 1,4 kali (9,1 x 10^-23 menjadi 1,3 x 10^-22). Pada simulasi di bawah, harga ini tidak terlihat untuk koalisi paling banyak c. Untuk 6 sampai 8 orang, tempat tahap 1 hanya kadang berhasil, peluang menangkap minimal satu anggota turun paling banyak 2 poin persentase.

**Tampilan.** Putusan tetap putusan tahap 1, dan tahap lanjutan hanya berjalan setelah tahap 1 menyebut nama. Halaman Lacak, CLI, JSON, dan berita acara menulis nama tahap lanjutan bersama dasarnya, misalnya "tahap 2: dituduh berdasarkan salinan yang sudah dituduh #3, #7", dengan skor tahap, ambang tahap, dan peluang tuduhan salahnya sendiri. Di halaman Lacak nama itu tampil di bawah nama tahap 1 dan lebih kecil, dan tabel di Bukti per kanal merangkum setiap tahap lanjutan: dasar, posisi tak terjelaskan, ambang, jatah eps, dan salinan yang dituduh. Peringkat skor di halaman itu tetap skor tahap 1. Salinan yang dituduh di tahap lanjutan disebut namanya di sana hanya bersama dasar, skor tahap, dan ambang tahapnya. Di berita acara baris "Peringkat" tahap 1 tetap tanpa identitas, dan nama itu ada di tabel tahapnya.

**Angka.** `research/bertahap/ukur.py`; grid, benih, dan kebijakan ditetapkan sebelum simulasi dijalankan, angka mentah di `research/bertahap/hasil/`. Kode c = 3, eps = 10^-6 sebagai jatah satu pelacakan, pembacaan penuh tanpa derau, 1.000 percobaan per strategi. Rentang mencakup 7 strategi termasuk terburuk; strategi hapus dibahas di bawah.

| N = 100, koalisi | Anggota tertangkap, satu tahap | Bertahap | Semua tertangkap, satu tahap | Bertahap | Minimal 1 tertangkap, satu tahap / bertahap |
|---|---|---|---|---|---|
| 4 | 99,7 sampai 100 % | 99,8 sampai 100 % | 98,9 sampai 99,9 % | 99,2 sampai 100 % | 100 / 100 % |
| 5 | 85 sampai 86 % | 87 sampai 100 % | 44 sampai 47 % | 48 sampai 100 % | 100 / 100 % |
| 6 | 39 sampai 44 % | 70 sampai 96 % | 0,2 sampai 1,4 % | 22 sampai 96 % | 94 sampai 98 / 94 sampai 98 % |
| 7 | 12 sampai 14 % | 29,5 sampai 56 % | 0 % | 0,9 sampai 55 % | 59 sampai 65 / 58 sampai 64 % |
| 8 | 3,3 sampai 3,7 % | 6 sampai 19 % | 0 % | 0 sampai 14 % | 24 sampai 26 / 22 sampai 25 % |

Untuk N = 20 angkanya serupa: anggota tertangkap 83 sampai 86 % menjadi 87 sampai 100 % (5 orang), 39 sampai 44 % menjadi 67 sampai 96 % (6 orang), 14 sampai 15 % menjadi 30 sampai 61 % (7 orang), dan 4 sampai 5 % menjadi 7 sampai 20 % (8 orang).

* **Batas bawah rentang** berasal dari strategi mayoritas (5 dan 6 orang) dan campur acak (7 dan 8 orang). Bit mayoritas hampir selalu dimiliki salinan yang sudah dituduh, jadi posisi tak terjelaskan jarang ada: untuk 5 orang anggota tertangkap hanya naik dari 86 menjadi 87 %. Strategi minoritas dan terburuk, yang paling menekan tahap 1, paling terbantu: untuk 6 orang dari sekitar 39 % menjadi sekitar 94 %.
* **Strategi hapus** tertangkap semua atau tidak sama sekali, karena posisi yang tersisa sama di semua salinan koalisi. Sampai 7 orang hasilnya 100 %; untuk 8 orang turun dari 92,7 menjadi 90,7 % (N = 100) karena ambang tahap 1 sedikit lebih tinggi.
* **Koalisi paling banyak c** (1, 2, dan 3 orang, N = 20 dan 100): semua anggota tertangkap pada semua percobaan, dengan dan tanpa tahap lanjutan. Dengan kanal berderau (5 % bit salah, 35 % terhapus, N = 100, 3 orang), anggota tertangkap 99,3 sampai 99,7 % menjadi 99,5 sampai 100 %, dan semua tertangkap 97,9 sampai 99,0 % menjadi 98,5 sampai 100 %.
* **Tuduhan salah.** Nol di semua tahap dalam 136.000 percobaan (17 sel, 8 strategi, 1.000 percobaan per strategi). Skor tertinggi penerima tak bersalah adalah 79 % dari ambang di tahap 1, 74 % di tahap 2, 66 % di tahap 3, dan 62 % di tahap 4. Pada target yang dapat diukur, skor penerima tak bersalah di tahap 2 sampai 4 melewati ambang tahapnya pada laju 1,1 x 10^-3 untuk target 10^-2 dan 9,3 x 10^-5 untuk target 10^-3, dari 3,28 juta skor. Keduanya di bawah batasnya.

## Aturan keluaran

Nama hanya muncul bersama skor, ambang, dan peluang tuduhan salahnya. Bila tidak ada salinan yang melewati ambang, keluarannya "tidak cukup bukti" dan tidak ada nama yang disebut. Nama dari tahap lanjutan pelacakan bertahap selalu muncul bersama salinan yang menjadi dasarnya.

## Arsitektur

```
            +---------------- Terbitkan -----------------+          +------------------ Lacak -------------------+
 PDF induk  |  layout   rencana penandaan (kunci)        |  salinan | foto / tangkapan layar / PDF / DOCX / teks |
 + penerima |  model -> geser, latar, teks, semantik,    |--------->|  rectify (kontur, SIFT, Tesseract) + ECC   |
            |           pilihan kata, kanari -> render   |          |  ch_shift  ch_background  ch_zerowidth     |
            |           ulang + gerbang -> 20 salinan    |          |  ch_semantic  ch_lexical  ch_docx          |
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
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), spending (jatah eps),
                staged (pelacakan bertahap), detection, attacks, simulate
  marker/       layout, master (font), plan, pdf_shift, background, pdf_zerowidth, semantic, lexical,
                canary, docx_marker, render (gambar ulang + gerbang visual), raster (halaman pindaian),
                issue (paralel)
  decoder/      rectify, lines (Tesseract), ch_shift, ch_background, ch_zerowidth, ch_semantic, ch_lexical,
                ch_docx, image, ocr (teks terlihat pada bukti gambar), fuse, accuse, erasure (pola penghapusan),
                contradiction (bacaan jelas tanpa nama), trace, report (berita acara)
  assets/       font DejaVu, leksikon pilihan kata (leksikon/naskah_dinas_v1.json, draf)
  registry/     chain (rantai hash, trigger tambah-saja), signing (Ed25519), verify, merkle
  canary_dns/   server (dnslib), store (log berantai)
  llm/          provider (antarmuka), mock (deterministik), llamacpp (lokal, loopback saja)
  web/          FastAPI + HTMX, antarmuka berbahasa Indonesia
  photos.py     simulator foto, tangkapan layar, dan printer
  ponsel.py     ISP ponsel dan monitor simulasi untuk photos.py (opsional)
  ketik.py      simulator pengetikan ulang dan OCR (untuk pengujian dan pengukuran)
  collusion.py  serangan koalisi yang menghapus tanda di bagian yang sama (riset dan pengujian)
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
scripts/        alat ukur dan eksperimen (scripts/cetak: pengukuran salinan cetak)
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
research/ketik/ pengukuran kanal pilihan kata (kapasitas, galat baca, atribusi)
research/pindaian/ pengukuran induk hasil pindai (protokol, hasil, potongan gambar)
research/ponsel/ pengukuran foto ponsel dan foto layar simulasi (protokol, pemilihan dekoder, hasil)
research/layar/ tangkapan layar dari penggambar PDF sungguhan (protokol, letak glif, pemilihan dekoder, hasil)
research/ocr/   OCR bukti gambar untuk varian kalimat dan pilihan kata (protokol, pemilihan pengaturan, hasil)
research/sepakat/ koalisi yang memahami TAPAK: serangan, pemeriksaan pola penghapusan, penyamaran
research/kontradiksi/ pemeriksaan bacaan jelas tanpa nama dan pemeriksaan pola penghapusan pada cetakan
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
| terburuk (rata-rata skor koalisi terendah; untuk c = 3 sama dengan minoritas) | 0 / 1.000 | 100 % | 100 % | 372,5 | 768,1 |

Batas terbukti peluang koalisi ini lolos adalah 1,2 x 10^-25 ([batas deteksi terbukti](#batas-deteksi-terbukti)). Skor tertinggi penerima tak bersalah di seluruh percobaan adalah 72 % dari ambang. Nol tuduhan salah dalam 1.000 percobaan hanya menunjukkan bahwa lajunya kira-kira di bawah 3 x 10^-3, jadi batasnya juga diuji pada tingkat yang dapat diukur. Pada target 10^-2 laju empirisnya 6,6 x 10^-4, dan pada target 10^-3 lajunya 2,8 x 10^-5 (dari 679.000 skor penerima tak bersalah, termasuk skor strategi terburuk yang mengulang skor minoritas). Hasil ini konsisten dengan batas Chernoff yang konservatif. Pada 10^-6 batasnya tidak dapat diuji dengan sampling; jaminannya berasal dari batas matematis.

Uji tambahan (berkas lengkap di [`results/`](results/)):

| Skenario | Tuduhan salah | Deteksi | Semua tertangkap |
|---|---|---|---|
| N=20, c=3 (m=2987) | 0 | 100 % | 100 % |
| N=100, c=3, kanal berderau: 5 % bit salah, 35 % terhapus | 0 | 100 % | 98 sampai 100 % |
| N=100, kode untuk c=3 diserang 5 orang (di luar rancangan), 300 percobaan | 0 | 100 % | 42 sampai 49 % (strategi hapus: 100 %) |
| sama, [pelacakan bertahap](#pelacakan-bertahap), 1.000 percobaan | 0 | 100 % | 48 sampai 100 % (mayoritas 48 %, 6 strategi lain dan hapus 100 %) |

Untuk kanal berderau di baris kedua, batas terbukti peluang koalisi paling banyak 3 orang lolos adalah 3,4 x 10^-5 (`tapak deteksi --n 100 --ber 0.05 --erasure 0.35`; [bit salah dan bobot lunak](#bit-salah-dan-bobot-lunak)).

Tabel parameter (eps = 10^-6, `tapak simulate --table`):

| N | c | eps1 | m (K=2 pi^2) | m (K=100) | Z Chernoff | Z Gauss | rata-rata skor kolusi per anggota | batas lolos terbukti (K=2 pi^2) |
|---|---|---|---|---|---|---|---|---|
| 20 | 2 / 3 / 5 | 5e-8 | 1328 / 2987 / 8297 | 6725 / 15131 / 42029 | 233 / 340 / 552 | 194 / 291 / 485 | 423 / 634 / 1056 | 5e-17 / 2e-23 / 2e-38 |
| 50 | 2 / 3 / 5 | 2e-8 | 1400 / 3150 / 8749 | 7092 / 15955 / 44319 | 246 / 359 / 582 | 205 / 308 / 514 | 446 / 668 / 1114 | 7e-18 / 1e-24 / 1e-40 |
| 100 | 2 / 3 / 5 | 1e-8 | 1455 / 3273 / 9091 | 7369 / 16579 / 46052 | 256 / 373 / 605 | 214 / 321 / 535 | 463 / 695 / 1158 | 2e-18 / 1e-25 / 4e-42 |
| 500 | 2 / 3 / 5 | 2e-9 | 1582 / 3559 / 9885 | 8013 / 18028 / 50076 | 278 / 405 / 658 | 234 / 351 / 585 | 504 / 755 / 1259 | 4e-20 / 8e-28 / 1e-45 |

### Batas deteksi terbukti

Simulasi hanya menunjukkan bahwa koalisi selalu tertangkap dalam percobaan yang dijalankan. `tapak/tardos/detection.py` memberi batas atas peluang sebaliknya, yaitu tidak satu pun anggota koalisi mencapai ambang. Batas ini berlaku untuk setiap strategi yang mematuhi asumsi penandaan, tanpa pendekatan asimtotik atau Gauss.

* **Caranya.** Bila tidak ada anggota yang mencapai Z, jumlah skor koalisi di bawah c x Z. Jumlah itu adalah jumlah per posisi yang hanya bergantung pada banyaknya bit 1 di antara anggota, bit yang dibocorkan, dan bias posisi itu. Koalisi tidak tahu biasnya, jadi faktor Chernoff tiap posisi dapat dimaksimalkan atas pilihan bit bocor secara terpisah. Hasilnya berlaku untuk strategi apa pun, termasuk yang acak atau memakai posisi lain. Ambang Z yang ikut berubah dengan vektor bias dibatasi oleh fungsi Chernoff-nya sendiri. Integral atas sebaran bias dihitung dengan kuadratur Gauss-Legendre dan diperiksa dengan kisi dua kali lebih rapat. Turunan lengkapnya ada di docstring modul.
* **Cakupan.** Pembacaan penuh dengan bit pasti, juga penghapusan di posisi tempat salinan koalisi berbeda (strategi hapus) dan penghapusan yang tidak bergantung pada kode (batasnya lalu dihitung dengan jumlah posisi yang terbaca). Bit salah dan bobot lunak tercakup dengan syarat pada kanal ([di bawah](#bit-salah-dan-bobot-lunak)). Penghapusan yang menyasar posisi tempat salinan koalisi sama hanya diukur ([batasan 12](keamanan.md#batasan), [koalisi yang memahami TAPAK](#koalisi-yang-memahami-tapak)).
* **Strategi terburuk.** Strategi `worst-case` (terburuk) membocorkan bit yang membuat rata-rata skor koalisi per posisi paling kecil. Dengan sebaran bias TAPAK, rumus tertutupnya menunjukkan bahwa ini selalu bit minoritas. Faktor Chernoff justru terbesar untuk bit mayoritas pada parameter TAPAK, karena ekor bawah skornya lebih berat. Keduanya ikut dalam simulasi, dan batasnya berlaku untuk keduanya.

| c | batas lolos terbukti, K = 2 pi^2 (N = 20 / 100) | K untuk batas 10^-3 (N = 20 / 100) | K untuk batas 10^-6 (N = 20 / 100) |
|---|---|---|---|
| 2 | 5 x 10^-17 / 2 x 10^-18 | 10,9 / 10,7 | 13,3 / 12,9 |
| 3 | 2 x 10^-23 / 1 x 10^-25 | 9,7 / 9,5 | 11,7 / 11,4 |
| 4 | 5 x 10^-31 / 6 x 10^-34 | 9,0 / 8,8 | 10,6 / 10,4 |
| 5 | 2 x 10^-38 / 4 x 10^-42 | 8,5 / 8,4 | 9,9 / 9,7 |

Batas ini mencakup setiap koalisi berukuran paling banyak c dan memakai ambang pembacaan penuh untuk seluruh eps. Pelacakan yang tercatat memakai jatah eps yang lebih kecil, jadi ambangnya lebih tinggi dan batasnya naik pelan dengan nomor pelacakan: untuk N paling sedikit 20, paling besar 2,4 x 10^-16 pada pelacakan pertama, 5,3 x 10^-12 pada pelacakan ke-10, dan 1,7 x 10^-8 pada pelacakan ke-100, dengan ambang tahap 1 [pelacakan bertahap](#pelacakan-bertahap) (tanpa tahap: 2 x 10^-16, 4,3 x 10^-12, dan 1,4 x 10^-8; angka mentah di `research/bertahap/hasil/batas.jsonl`). Batas ini hanya untuk tahap 1; yang ditambahkan tahap lanjutan hanya diukur. Untuk N di bawah 20 batasnya juga sedikit lebih besar (4,5 x 10^-14 untuk c = 2 dan N = 1, seluruh eps). Jadi konstanta bawaan cukup dengan margin lebar.

Perbandingan dengan simulasi (`research/deteksi/ukur.py`; grid ditetapkan sebelum simulasi dijalankan, angka mentah di `research/deteksi/hasil/`): c = 2 sampai 5, N = 20 dan 100, 8 strategi, 1.000 percobaan per strategi. Pada panjang bawaan tidak ada koalisi yang lolos. Pada kode pendek yang sengaja dibuat lemah:

| Batas terbukti | 0,9 | 0,5 | 0,1 | 0,01 |
|---|---|---|---|---|
| Panjang kode (c = 3, N = 20) | 973 | 1070 | 1212 | 1353 |
| Laju lolos terukur tertinggi (semua c, N, dan strategi) | 14 % | 4,4 % | 0,6 % | 0,1 % |

Tidak ada laju terukur yang melampaui batasnya, dan tidak ada tuduhan salah. Batasnya longgar: laju terukur tertinggi 6 sampai 17 kali lebih kecil.

Strategi terburuk hanya terburuk untuk rata-rata skor per posisi, dan kedelapan strategi itu memilih bit dari satu posisi saja. Pemeriksaan ulang (`research/deteksi/penyeimbang.py`, c = 2 sampai 4, N = 20, 2.000 percobaan per sel) memakai koalisi yang melihat semua posisi dan memilih bit agar perkiraan skor anggotanya tetap sama rata. Koalisi ini lolos sampai 4 kali lebih sering daripada strategi terbaik di atas: paling tinggi 22 %, 6 %, dan 0,65 % pada batas 0,9, 0,5, dan 0,1. Itu tetap di bawah batasnya; batasnya 4 sampai 15 kali lebih besar. Batas terbukti berlaku untuk strategi seperti ini juga; simulasi hanya memeriksa contoh yang kami coba. Batas itu mengecil secara eksponensial terhadap m, jadi pada panjang bawaan pun sudah sangat kecil.

#### Bit salah dan bobot lunak

Dekoder tidak melihat kata bocoran y, tetapi bacaannya: bit yang mungkin terbalik dan bobot w_i = tanh(|LLR|/2). Bit yang terbalik membalik tanda skor koalisi di posisi itu, jadi rata-rata skor koalisi menyusut menjadi w_i (1 - 2 e_i) kali semula, dengan e_i peluang bit itu terbalik. Ambang Z(p, w) dibatasi seperti pada pembacaan penuh, dengan fungsi Chernoff berbobot yang memang dipakai TAPAK. Buktinya memerlukan dua syarat:

1. Derau kanal terjadi setelah koalisi memilih bitnya, dan tidak bergantung pada kode, pada pilihan koalisi, maupun pada bit yang dibocorkan. Kanal simetris memenuhinya: |LLR| dan benar-salahnya keputusan hanya bergantung pada derau.
2. Dengan bobot diketahui, bit yang terbalik saling bebas antarposisi, dengan laju e_i yang diketahui.

Syarat 1 menjamin bahwa, dengan bobot diketahui, kode masih tersebar seperti tanpa kanal, sehingga batas Chernoff tetap terpecah menjadi hasil kali per posisi. Syarat 2 membuat faktor setiap posisi menjadi rata-rata dua kemungkinan (terbalik atau tidak) di dalam maksimum atas bit bocor. Hasilnya batas peluang lolos bila bobot yang terbaca diketahui (`read_miss_bound`) dan bila setiap posisi, bebas dari posisi lain, mengambil bobot dan laju salahnya dari satu sebaran (`channel_miss_bound`, juga di `tapak deteksi`). Batas kedua juga mencakup strategi hapus, tetapi tidak berlaku untuk satu bacaan yang bobotnya bergerak bersama (foto yang baik atau buruk secara keseluruhan); untuk bacaan seperti itu batasnya dihitung dari bobotnya sendiri. Tanpa derau (w = 1, e = 0) hasilnya sama dengan batas pembacaan penuh. Bila syarat 1 gagal, misalnya bobot nol justru jatuh di posisi tempat salinan koalisi sama, sebaran kode di posisi yang terbaca berubah dan batasnya tidak berlaku (tabel terakhir di bawah). Dekoder foto TAPAK sendiri tidak memenuhi syarat 1 secara persis: kanal latar memakai vektor bias sebagai pilot untuk memperkirakan penguatannya per strata dan untuk memutuskan ada tidaknya pola, jadi bobotnya bergantung pada kode lewat beberapa angka bersama untuk satu halaman. Pengaruhnya per posisi kecil, tetapi tidak dimodelkan. Turunan lengkapnya ada di docstring `tapak/tardos/detection.py`.

Sebaran bobot dekoder diukur pada 40 foto layar dan tangkapan layar sintetis dari benchmark (`research/deteksi/llr_foto.py`, angka di `research/deteksi/hasil/llr_foto.json`). Dari posisi yang terbaca, 82 % berbobot di atas 0,95 dan 4 % terhapus. Di bobot menengah laju salahnya beberapa poin persentase di atas atau di bawah laju terkalibrasi (1 - w)/2, tetapi di bobot tertinggi dekoder terlalu yakin: bobot di atas 0,95 (rata-rata 0,998) salah 0,33 %, 2,8 kali perkiraan 0,12 %, dan bobot 0,9 sampai 0,95 salah 5,3 %, 1,5 kali perkiraannya. Karena itu batas dengan laju (1 - w)/2 tidak sah untuk foto ini, dan model "foto" di bawah memakai laju salah terukur per kelompok bobot. Laju itu juga berbeda per foto: jumlah bit salah tiap foto 0,5 sampai 4,3 kali perkiraan terkalibrasinya. Foto dengan lebih dari 100 bit salah terkalibrasi baik (0,85 sampai 1,14 kali), sedangkan foto bersih dan tangkapan layar yang hanya salah beberapa bit cenderung terlalu yakin.

Sebaran ini menggabungkan posisi dari 40 gambar, dan setiap gambar hanya memuat halaman 1 (sekitar 1.990 dari 2.987 posisi). Di dalam satu foto bobot tidak bebas antarposisi: foto baik atau buruk secara keseluruhan (jumlah w^2 per foto 86 sampai 1.986). Jadi kolom "bobot foto" di bawah adalah batas untuk pembacaan semua posisi dengan bobot seperti foto yang diundi bebas per posisi, bukan batas untuk satu foto. Batas satu foto dihitung dari bobotnya sendiri (`read_miss_bound`; `research/deteksi/baca_foto.py`, angka di `research/deteksi/hasil/baca_foto.jsonl`). Dengan laju salah terukur gabungan per kelompok bobot, untuk koalisi paling banyak 3 orang batasnya paling kecil 6 x 10^-9 (tangkapan layar) dan mediannya 2 x 10^-8. Pada 9 dari 40 gambar batasnya di atas 10^-6, dan 5 gambar tidak memberi jaminan (0,85 sampai 1). Sebaran gabungan memberi 1 x 10^-17 untuk kode yang sama.

**Plafon laju salah** (`read_miss_ceiling`). Syarat 2 meminta laju salah yang tepat, padahal dekoder paling banyak tahu batas atasnya. Dua sifat faktor per posisi menutup hal itu dan sekaligus membuat satu bacaan dengan ribuan bobot berbeda murah dihitung: faktornya cembung terhadap laju salah, dan logaritmanya cembung terhadap bobot. Jadi untuk semua posisi yang bobotnya di dalam satu kotak [w_bawah, w_atas] dan laju salah sebenarnya di antara 0 dan plafonnya, faktornya tidak melebihi faktor terbesar di keempat sudut kotak. Bobot bacaan dibagi menjadi paling banyak 64 kotak, dan ambang Z(p, w) tetap dihitung dari bobot yang tepat. Hasilnya batas atas P(lolos | bobot) untuk setiap kanal yang memenuhi syarat 1 dan laju salahnya tidak melebihi plafon. Batas ini tidak pernah lebih kecil dari `read_miss_bound` dengan laju yang sama (pada bacaan sintetis dengan 64 kotak paling banyak 0,3 lebih besar dalam log10) dan memerlukan sekitar 0,2 detik per ukuran koalisi. Pemeriksaan bacaan jelas tanpa nama ([di bawah](#pemeriksaan-bacaan-jelas-tanpa-nama)) memakainya.

Batas pada panjang bawaan (K = 2 pi^2, N = 20, seluruh eps, koalisi paling banyak c):

| c | bit pasti | bit salah 2 % | 5 % | 10 % | 20 % | bobot foto, laju terukur | K untuk batas 10^-6: bit salah 5 % / 10 % / 20 % / bobot foto |
|---|---|---|---|---|---|---|---|
| 2 | 5 x 10^-17 | 2 x 10^-14 | 7 x 10^-11 | 4 x 10^-6 | 0,40 | 1 x 10^-12 | 16,3 / 20,4 / 35,8 / 15,2 |
| 3 | 2 x 10^-23 | 5 x 10^-20 | 3 x 10^-15 | 8 x 10^-9 | 0,21 | 1 x 10^-17 | 14,3 / 17,9 / 31,2 / 13,4 |
| 4 | 5 x 10^-31 | 2 x 10^-26 | 3 x 10^-20 | 1 x 10^-11 | 0,10 | 2 x 10^-23 | 13,0 / 16,3 / 28,6 / 12,2 |
| 5 | 2 x 10^-38 | 9 x 10^-33 | 5 x 10^-25 | 2 x 10^-14 | 0,05 | 4 x 10^-29 | 12,2 / 15,3 / 26,9 / 11,4 |

Bit pasti memerlukan K 13,3 / 11,7 / 10,6 / 9,9 untuk 10^-6 (tabel sebelumnya). Dengan 10 % bit salah, K bawaan masih cukup untuk 10^-6 kecuali pada c = 2 (perlu 20,4). Dengan 20 % bit salah, kode bawaan tidak memberi jaminan yang berarti (batas 0,05 sampai 0,40). Laju terkalibrasi (1 - w)/2 memberi batas sedikit lebih kecil daripada laju terukur, tetapi tidak sah untuk foto. Untuk N = 100 batasnya sedikit lebih kecil (angka mentah di `research/deteksi/hasil/batas_kanal.jsonl`).

Perbandingan dengan simulasi (`research/deteksi/kanal.py`, bagian `derau`; grid ditetapkan dan dicatat di git sebelum simulasi dijalankan): N = 20, c = 2 sampai 5, 8 strategi, 1.000 percobaan per sel. Panjang kode setiap sel adalah kode terpendek yang batasnya 0,5 atau 0,1 untuk model baca itu, dihitung dari batas saja. Bit salah dan bobot diundi per posisi setelah koalisi memilih bitnya, dan ambang Z(p, w) dihitung dari bobot yang terbaca, seperti di dekoder. "Bobot foto" berarti bobot diundi dari sebaran terukur di atas; bit salahnya diundi bebas dari bobot, kecuali di dua baris terakhir.

| Model baca | K untuk batas 0,5 (c = 2 sampai 5) | Laju lolos tertinggi | K untuk batas 0,1 | Laju lolos tertinggi |
|---|---|---|---|---|
| bobot 1, tanpa bit salah | 6,5 sampai 7,7 | 3,9 % | 7,2 sampai 8,8 | 0,4 % |
| bobot 1, bit salah 2 % | 7,0 sampai 8,2 | 4,6 % | 7,8 sampai 9,5 | 0,5 % |
| bobot 1, bit salah 5 % | 7,9 sampai 9,2 | 4,1 % | 8,8 sampai 10,7 | 0,4 % |
| bobot 1, bit salah 10 % | 9,8 sampai 11,4 | 4,9 % | 11,0 sampai 13,2 | 0,7 % |
| bobot 1, bit salah 20 % | 16,9 sampai 19,2 | 5,9 % | 19,0 sampai 22,6 | 0,5 % |
| bobot foto, tanpa bit salah | 7,0 sampai 8,3 | 4,6 % | 7,7 sampai 9,5 | 0,8 % |
| bobot foto, bit salah 2 % | 7,5 sampai 8,9 | 4,4 % | 8,4 sampai 10,2 | 0,5 % |
| bobot foto, bit salah 5 % | 8,4 sampai 9,9 | 5,3 % | 9,4 sampai 11,5 | 0,5 % |
| bobot foto, bit salah 10 % | 10,5 sampai 12,3 | 4,9 % | 11,8 sampai 14,2 | 0,5 % |
| bobot foto, bit salah 20 % | 18,1 sampai 20,6 | 4,9 % | 20,4 sampai 24,3 | 0,6 % |
| bobot foto, laju (1 - w)/2 | 7,3 sampai 8,7 | 4,5 % | 8,2 sampai 10,0 | 0,4 % |
| bobot foto, laju terukur (model foto) | 7,4 sampai 8,7 | 4,8 % | 8,2 sampai 10,1 | 0,5 % |

Di 96 sel (768.000 serangan) tidak ada laju lolos yang melampaui batasnya. Laju terukur tertinggi 5,9 % untuk batas 0,5 dan 0,8 % untuk batas 0,1, jadi batasnya 8 sampai 12 kali di atas laju terukur tertinggi. Batasnya makin longgar untuk koalisi besar: 8 sampai 12 kali untuk c = 2, 20 sampai 23 kali untuk c = 3, 33 sampai 45 kali untuk c = 4, dan 71 sampai 100 kali untuk c = 5 (di 9 sel dengan batas 0,1 tidak ada koalisi yang lolos). Strategi yang paling sering lolos berbeda dari sel ke sel. Harga bit salah terlihat di kolom K: dengan 20 % bit salah, kode perlu sekitar 2,5 kali lebih panjang untuk batas yang sama, mendekati faktor 1/(1 - 2e)^2 = 2,8.

Penghapusan yang menyasar posisi tempat salinan koalisi sama (`kanal.py`, bagian `sasaran`; panjang bawaan, N = 20, pembacaan tanpa bit salah, 8 strategi, 1.000 percobaan per sel). Koalisi melihat di mana salinannya sama, dan asumsi penandaan saja tidak melarang menghapus tanda di sana. Setiap posisi itu dihapus dengan peluang r, di atas strategi biasa di posisi yang berbeda:

| r | 0 | 50 % | 80 % | 90 % sampai 100 % |
|---|---|---|---|---|
| Laju lolos tertinggi, c = 2 / 3 / 4 / 5 | 0 / 0 / 0 / 0 | 1,6 / 0,5 / 0,3 / 0 % | 99,9 / 96 / 96 / 97 % | 99,4 sampai 100 % untuk setiap strategi |
| Batas untuk penghapusan acak yang menyisakan jumlah posisi sama (tidak berlaku di sini) | 5 x 10^-17 sampai 2 x 10^-38 | 1 x 10^-5 sampai 2 x 10^-21 | 0,29 sampai 1 x 10^-12 | 1 sampai 4 x 10^-10 |

Posisi tempat salinan koalisi sama membawa hampir seluruh skor koalisi. Bila separuhnya masih terbaca, deteksi tetap hampir pasti; bila sebagian besar terhapus, koalisi lolos, jauh di atas batas yang berlaku untuk penghapusan acak. Penghapusan seperti ini menuntut koalisi menghapus tanda di bagian yang salinannya sama (misalnya meratakan pola latar di sana) tanpa menyentuh bagian yang berbeda. Batas terbukti tidak mencakupnya. Pada salinan sungguhan hal itu ternyata mudah dilakukan ([di bawah](#koalisi-yang-memahami-tapak)).

## Koalisi yang memahami TAPAK

Kode TAPAK terbuka; hanya kuncinya yang rahasia. Koalisi yang memegang dua salinan atau lebih dapat membandingkannya, melihat persis di bagian mana salinannya sama, lalu menghapus tanda hanya di sana. `research/sepakat/` mengukurnya pada salinan sungguhan. Protokol, benih, dan aturan keputusan ditetapkan dan dicatat di git sebelum pengukuran; setiap pilihan dibuat dengan benih pengembangan, dan benih uji dijalankan sekali.

**Serangannya** (`tapak/collusion.py`; setiap keputusan hanya berasal dari salinan koalisi):

* **Pola latar.** Setiap salinan menyimpan polanya sebagai satu gambar di bawah teks. Koalisi membaca tingkat setiap sel dari gambar itu, tanpa kunci, dan membandingkan salinannya. Delapan sel satu posisi kode selalu sama atau berbeda bersama-sama, jadi koalisi tahu persis sel mana yang membawa bit yang sama (setiap sel terbaca tepat; pengujian memeriksanya terhadap kode). Sel itu diratakan ke tingkat dasar.
* **Geser.** Letak kelompok kata dan baris dibaca dari PDF, dan unit data mengikuti aturan tata letak yang terbuka dari skema gesernya. Kelompok yang berada di tempat yang sama di semua salinan membawa bit yang sama. Letaknya di dokumen induk ditaksir dari tipografi.
  * **Skema v1.** Di dokumen contoh, jarak kata di kiri dan kanan kelompok data sama, sehingga selisihnya menunjukkan arah geser. Satu salinan saja sudah mengungkap arah geser 96 % kelompok kata dan 49 % baris nota dinas (surat telegram: 95 % dan 38 %), semuanya benar. Kelompok itu dikembalikan ke garis antara kedua tetangga kendalinya.
  * **Skema v2.** Setiap kelompok kata ikut bergeser, jadi koalisi membaca satu baris sekaligus (`row_signs`). Semua jarak kata satu baris sama di dokumen induk, sehingga jarak di salinan menunjukkan pola tanda seluruh baris; pola terbaik dicari tepat dengan pemrograman dinamis, dengan tanda kelompok yang berbeda antarsalinan sudah diketahui. Jarak yang tidak dapat dijelaskan (label atau tab) memotong baris, dan kelompok yang jaraknya dapat dijelaskan dua arah belum diputuskan. Sisanya lalu dijangkarkan pada dokumen sebagai keseluruhan (`anchored_sign`, ditambahkan saat peninjauan): banyak kelompok berbagi tepi kolom di dokumen induk (margin kiri, inden daftar, tab sesudah label, margin kanan teks rata kiri-kanan), dan jarak antarbaris satu dokumen hanya beberapa nilai yang berulang, jadi tepi dan jarak induk unit yang sudah diketahui menentukan tanda unit lainnya. Satu salinan v2 mengungkap arah geser 98,8 % kelompok kata dan 89 % baris nota dinas (surat telegram: 99,1 % dan 90 %), 20 salinan per dokumen dengan benih baru; hanya satu kelompok dari 4.521 yang salah. Tanpa penjangkaran 91 % dan 92 % kelompok kata, dan baris 49 % dan 38 % seperti v1. Penjangkaran baris berlaku juga untuk dokumen v1, yang barisnya sama; angka v1 di atas diukur tanpanya. Kelompok yang sama dikembalikan ke letak induk taksirannya.
* **Di posisi yang berbeda** koalisi memakai anggota acak per sel atau per kelompok (`acak`), salinan pertama (`salin`), atau rata-rata salinan (`rata`). Varian yang lebih murah hanya menghapus pola latar (`latar`) atau hanya geser (`geser`); yang lengkap menghapus keduanya (`semua`). PDF hasilnya juga tanpa karakter tak terlihat dan huruf kembar.

**Angka, skema v1** (benih uji: nota dinas dan surat telegram, N = 20 dan 100, koalisi 2, 3, dan 4 salinan, 5 koalisi per sel, jadi 60 koalisi per kanal; pelacakan pertama yang tercatat). Bukti dibuat dari PDF hasil serangan: berkas PDF itu sendiri, tangkapan layar halaman 1, foto layar halaman 1, dan foto halaman 1 dan 2 yang dicetak printer laser simulasi. "Lolos" berarti tidak satu pun anggota disebut, juga dengan pelacakan bertahap; "terdeteksi" berarti [pemeriksaan pola penghapusan](#pemeriksaan-pola-penghapusan) memberi peringatan.

Setiap sel berisi lolos / terdeteksi, dari 60 bukti:

| Kanal | Salinan pertama, jujur: disebut benar | semua/acak | latar/acak | geser/acak | semua/salin | semua/rata |
|---|---|---|---|---|---|---|
| PDF | 60 | 60 / 60 | 60 / 60 | 0 / 0 | 0 / 60 | 60 / 40 |
| tangkapan layar | 60 | 60 / 60 | 60 / 60 | 0 / 0 | 8 / 60 | 60 / 37 |
| foto layar | 58 | 60 / 54 | 60 / 53 | 6 / 0 | 25 / 55 | 60 / 24 |
| foto cetakan, 2 halaman | 10 | 60 / 0 | - | - | 53 / 0 | - |

* **Tidak ada tuduhan salah** di 2.520 pelacakan benih uji (1.260 bukti, masing-masing satu tahap dan bertahap), juga di benih pengembangan. Pelacakan bertahap tidak mengubah angka lolos: bila tahap 1 tidak menyebut siapa pun, tahap lanjutan tidak berjalan.
* **Hapus semua yang sama** membuat koalisi lolos pada setiap bukti, di keempat kanal. Pola latar di posisi yang sama hilang seluruhnya, geser 85 sampai 87 % (diukur dari bobot bertanda di posisi itu, dibandingkan dengan salinan pertama yang jujur melalui kanal dan benih yang sama); kelompok yang tipografinya tidak memberi taksiran tetap membawa bitnya.
* **Hanya pola latar** sudah cukup untuk lolos, karena geser sendiri hanya membawa sekitar 100 posisi per halaman. **Hanya geser** tidak cukup: posisi latar yang sama tetap menunjuk koalisi (kecuali pada 6 dari 60 foto).
* **Salinan pertama di posisi yang berbeda** (`salin`) menyerahkan salinan itu: posisi yang berbeda membawa bitnya, dan pada PDF salinan itu selalu disebut. Pada tangkapan layar ia disebut 52 kali dan pada foto 35 kali dari 60. Dekoder latar foto menaksir penguatannya dari posisi pilot, yang biasnya dekat 0 atau 1, dan posisi itu hampir selalu posisi yang sama, yang sudah dihapus; bobot latar lalu runtuh.
* **Rata-rata dua salinan** menghapus semuanya, dan buktinya tampak seperti dokumen tanpa tanda; pemeriksaan tidak menandainya. Dengan 3 atau 4 salinan rata-rata menyisakan pola lemah di posisi yang berbeda, dan yang terhapus kembali posisi yang sama, sehingga sebagian besar ditandai.
* **Cetakan** dengan profil latar bawaan hanya membawa geser, dan salinan pertama yang jujur pun hanya disebut pada 10 dari 60, jadi koalisi lolos dengan mudah.

**Angka, skema v2** (`research/sepakat/geser2.py`: potongan protokol uji yang sama, ditetapkan sebelum dijalankan, pada penerbitan v2 dengan benih baru: nota dinas dan surat telegram, N = 20 dan 100, koalisi 2, 3, dan 4 salinan, 3 koalisi per sel, jadi 36 koalisi per kanal; anggota acak di posisi yang berbeda). `semua/hapus` dan `geser/hapus` sama dengan `semua/acak` dan `geser/acak` di atas, `semua/balik` membalik tanda alih-alih menghapusnya ([di bawah](#pemeriksaan-pola-penghapusan)). Potongan ini dijalankan dua kali dengan koalisi, benih, dan bukti yang sama: dengan taksiran per baris saja (`geser2_serang.jsonl`), lalu saat peninjauan dengan penjangkaran pada tepi kolom dan jarak baris (`geser2_serang_jangkar.jsonl`, ditetapkan sebelum dijalankan). Tabel memakai putaran kedua, serangan yang lebih kuat; putaran pertama memberi angka yang sama kecuali `geser/hapus` pada tangkapan layar (0 lolos). Setiap sel berisi lolos / terdeteksi, dari 36 bukti:

| Kanal | Salinan pertama, jujur: disebut benar | semua/hapus | geser/hapus | semua/balik |
|---|---|---|---|---|
| PDF | 36 | 36 / 36 | 0 / 0 | 36 / 0 |
| tangkapan layar | 36 | 36 / 36 | 1 / 0 | 36 / 0 |
| foto layar | 36 | 36 / 33 | 2 / 0 | 36 / 0 |
| foto cetakan, 2 halaman | 29 | 36 / 1 | - | 36 / 1 |

* **Tidak ada tuduhan salah** di 2.160 pelacakan (dua putaran, masing-masing 540 bukti, satu tahap dan bertahap).
* **Hapus semua yang sama** tetap membuat koalisi lolos pada setiap bukti. Dengan penjangkaran koalisi menetralkan 98,8 % unit geser yang sama menurut rencananya (1,2 % tanpa taksiran tipografi; dengan taksiran per baris saja 91 %); terukur pada bukti, geser di posisi yang sama hilang seluruhnya (99 sampai 101 %, rata-rata per kanal; dengan taksiran per baris saja 93 sampai 97 %; skema v1: 85 sampai 87 %), dan pola latar juga.
* **Cetakan berubah paling banyak.** Dengan skema v2 salinan pertama yang jujur disebut dari dua halaman cetak pada 29 dari 36 bukti (skema v1: 10 dari 60), jadi penghapusan kini benar-benar menghapus bukti yang ada. Peringatan hampir tidak muncul pada cetakan (1 dari 36), karena kekuatan baca latar yang hanya berisi derau (3.884 unit) menenggelamkan sekitar 440 unit geser: dihitung dari unit geser saja, Z cetakan yang sama mencapai ambang pada 19 dari 36 (median -3,2; diagnostik, bukan pemeriksaan yang dipasang). Satu cetakan yang ditandai di `semua/hapus` dan satu di `semua/balik` berasal dari koalisi yang sama dengan bilangan acak cetak dan foto yang sama; salinan jujurnya sudah membaca Z = -2,8 di sana, jadi itu nilai derau yang rendah, bukan penghapusannya.
* **Hanya geser** tidak cukup, seperti di skema v1: posisi latar yang sama tetap menunjuk koalisi, kecuali pada 2 dari 36 foto dan 1 dari 36 tangkapan layar. Peringatan tidak muncul karena pola latar di posisi yang berbeda ikut teracak (anggota acak per sel), sehingga Z justru positif.
* **Kekuatan baca geser v2 sendiri pendeteksi yang lemah.** Dihitung dari unit geser saja, hapus semua yang sama mencapai ambang pada 32 dari 36 PDF, tetapi hanya 13 dari 36 tangkapan layar dan 6 dari 36 foto; peringatan di sana terutama berasal dari pola latar. Bila sebagian besar kelompok satu baris dikembalikan ke letak induknya, offset baris membuat kelompok itu tampak seperti kelompok yang semuanya bergeser searah, jadi kekuatan bacanya tidak turun. Salinan pertama yang jujur tidak pernah mencapai ambang dari unit geser saja (0 dari 144).

Angka tingkat kode di atas (`kanal.py`, bagian `sasaran`) memperkirakan hal yang sama: dari 80 % posisi yang sama dihapus, koalisi hampir selalu lolos. Koalisi yang memahami TAPAK juga dapat menghapus semuanya: pola latar dengan membuang gambarnya, geser lewat tipografi, teks dengan membersihkan karakternya. Hasilnya selalu "tidak cukup bukti", tidak pernah tuduhan salah. Yang khas dari penghapusan yang menyasar kesamaan adalah bukti tetap tampak bertanda, dan itu yang diperiksa dekoder.

### Pemeriksaan pola penghapusan

Dekoder memeriksa apakah tanda hilang justru di posisi tempat salinan koalisi kemungkinan sama (`tapak/decoder/erasure.py`). Pemeriksaan ini memakai vektor bias dokumen, tidak pernah kode penerima, dan tidak mengubah ambang, skor, maupun putusan.

* **Gagasan.** Di posisi kode i, salinan koalisi sama dengan peluang p_i^c + (1 - p_i)^c, yang naik bersama q_i = (2 p_i - 1)^2 untuk setiap ukuran koalisi (untuk c = 2 dan 3 tepat linear). Penghapusan yang mengikuti kesamaan karena itu lebih sering mengenai posisi dengan q besar. Derau kanal tidak dapat melakukannya: vektor bias rahasia, slot dipasangkan dengan posisi lewat permutasi berkunci, dan tanda yang diputihkan tampak sama untuk bit 0 dan 1.
* **Kekuatan baca.** Dekoder geser dan latar melaporkan, untuk setiap unit yang diukur, seberapa jelas tandanya tanpa melihat bitnya: untuk geser jarak unit dari garis yang ditarik melalui tetangganya, dibagi sigma (0 bila pergeserannya tidak masuk akal), dan untuk latar |rata-rata terurai| serta energi sel (sel yang separuh lebih pikselnya jenuh putih tidak dihitung), juga bila pola latar tidak ditemukan; pemeriksaan kini hanya menghitung kekuatan baca latar dari halaman yang polanya ditemukan ([di bawah](#pemeriksaan-pola-penghapusan)). Pada skema v1 tetangga itu dua kelompok kendali yang tidak bergeser (|s|/sigma). Pada skema v2 setiap tetangga ikut bergeser, jadi tanda yang diharapkan dekoder dari setiap kelompok lain (0,025 mm kali rata-rata posterior tandanya) dikurangkan dulu, lalu garis baris dipasang melalui kelompok lain itu (`ch_shift.joint_strengths`). Kelompok yang terbaca jelas mendapat sekitar delta/sigma ke arah mana pun ia bergeser, kelompok yang dikembalikan ke letak induknya sekitar 0. Baris tetap memakai |s|/sigma.
* **Statistik.** Setiap ukuran diubah menjadi skor peringkat baku per keluaran kanal, skor di posisi yang sama dijumlahkan, lalu Z = r(skor, q) x akar(n - 1) atas n posisi terukur, r korelasi Pearson. Bila kekuatan baca tidak bergantung pada vektor bias, nilai q di posisi terukur adalah undian bebas dari sebaran bias, jadi Z bermean 0 dan bervarians tepat 1.
* **Ambang.** Peringatan muncul bila Z <= -3,09, kuantil normal untuk peluang alarm palsu 10^-3 yang ditetapkan sebelum pengukuran. Faktor kalibrasinya adalah simpangan baku Z pada 232 bukti jujur pengembangan (salinan tunggal lewat PDF, tangkapan layar, foto, dan cetakan), yaitu 1,00, jadi ambangnya tidak dinaikkan. Ambang yang sama berlaku untuk skema v2; di sana simpangan baku Z pada 480 salinan jujur dengan benih baru 0,96. Diperlukan sedikitnya 100 posisi terukur.
* **Tampilan.** Halaman Lacak, CLI, dan berita acara menulis di bawah putusan: "pola penghapusan disengaja terdeteksi: kemungkinan koalisi yang memahami TAPAK; bukti di posisi tempat salinan koalisi sama dihapus", dengan nilai Z dan ambangnya. Peringatan ini tidak menyebut siapa pun. Nilai Z selalu dicatat (JSON, berita acara, kotak keabsahan di halaman Lacak).

Terukur dengan benih uji (skema v1):

* **Serangan.** Hapus semua yang sama terdeteksi pada 60 dari 60 bukti PDF, 60 dari 60 tangkapan layar, 54 dari 60 foto layar, dan 0 dari 60 cetakan. Median Z per ukuran koalisi: -17 sampai -28 untuk PDF, -10 sampai -17 untuk tangkapan layar, dan -6 sampai -13 untuk foto. Di cetakan pola latar bawaan tidak sampai ke kertas, tetapi kekuatan baca latarnya (sekitar 3.000 posisi yang hanya berisi derau) tetap dihitung dan menenggelamkan sekitar 135 posisi geser. Rata-rata dua salinan tidak ditandai, dan memang tidak mengikuti kesamaan.
* **Bukti jujur.** Alarm palsu: 0 dari 232 bukti jujur pengembangan, 0 dari 240 salinan pertama yang jujur di set uji, dan 1 dari 64 bukti benchmark README saat masih diterbitkan dengan skema v1 (satu foto cetak satu halaman, Z = -3,14), jadi 1 dari 536. Rata-rata Z jujur per penerbitan dan kanal berkisar dari -1,3 sampai +1,7. Kualitas baca setiap slot sebagian sama di semua salinan satu dokumen (korelasi peringkat skor posisi antara dua salinan jujur 0,22 pada PDF dan 0,12 pada tangkapan layar nota dinas), sehingga Z jujur satu dokumen berpusat di sekitar nilai itu, bukan tepat 0. Laju 10^-3 berlaku rata-rata atas pembangkitan kode; untuk dokumen dengan pusat -1,3 lajunya sekitar 1 sampai 4 % (perkiraan normal). Diperiksa ulang dengan benih baru (`research/sepakat/balik.py`, 8 penerbitan, salinan 1 sampai 10 lewat keempat kanal): 1 alarm dari 320 bukti jujur (satu PDF surat telegram, Z = -3,29, dari dokumen yang pusat Z PDF-nya -1,39), dan 0 dari 24 bukti induk tanpa tanda; jadi 2 dari 856 bukti jujur. Pusat per dokumen paling menyebar pada PDF (simpangan baku antarpenerbitan sekitar 0,75 dari 14 penerbitan, tangkapan layar 0,4, foto dan cetakan hampir 0), dan peringatan menyebut bahwa untuk dokumen tertentu lajunya dapat sampai beberapa persen. Z serangan yang terdeteksi umumnya jauh di bawah ambang, sedangkan nilai yang hanya sedikit di bawah -3,09 adalah petunjuk lemah.
* **Koalisi yang tahu pemeriksaan ini menghindarinya tanpa biaya** (`research/sepakat/balik.py`, protokol ditetapkan sebelum dijalankan; benih baru, nota dinas dan surat telegram, N = 20 dan 100, koalisi 2, 3, dan 4 salinan, 36 koalisi per kanal). Cukup membalik tanda di posisi yang sama alih-alih menghapusnya: sel latar dinegasikan, kelompok data dicerminkan terhadap letak induknya. Setiap unit tetap terbaca sejelas salinan jujur, dan posisi yang dibalik justru menghitung melawan koalisi. Koalisi lolos pada 36 dari 36 bukti PDF, tangkapan layar, dan foto layar, dan tidak satu pun ditandai (median Z +14, +9, dan +6). Meratakan seluruh pola latar lalu menghapus geser yang sama saja juga lolos tanpa peringatan pada 36 dari 36 di ketiga kanal, karena kekuatan baca latar tanpa tanda menenggelamkan geser. Pembalikan melanggar asumsi penandaan, jadi batas terbukti pun tidak berlaku. Tidak ada tuduhan salah di 1.080 pelacakannya. Bit yang dibalik berlawanan dengan arah bias, dan itu terukur tanpa kode penerima (A / akar(B) dengan A = jumlah w (2y - 1)(2p - 1) dan B = jumlah w^2 (2p - 1)^2: median -4 sampai -32 pada bukti yang dibalik, +30 sampai +39 pada salinan jujur), tetapi uji seperti itu tidak dipasang: koalisi dapat meratakan pola latar dan membalik separuh unit geser secara acak sehingga A rata-rata 0, dan uji yang menangkap itu harus menganggap bobot dekoder terkalibrasi, jadi alarm palsunya tidak dapat dibatasi.

Terukur pada skema v2 (`research/sepakat/geser2.py`; protokol, benih baru, dan analisis ditetapkan sebelum dijalankan; kekuatan baca geser dari dekoder baris v2):

* **Bukti jujur.** Tidak ada alarm palsu: 0 dari 320 salinan jujur (salinan 1 sampai 10 dari 8 penerbitan, nota dinas dan surat telegram, N = 20 dan 100, lewat PDF, tangkapan layar, foto layar, dan dua halaman cetak), 0 dari 24 bukti induk tanpa tanda, dan 0 dari 128 pelacakan benchmark README, jadi 0 dari 472. Z terendah -2,72. Per kanal simpangan baku Z 0,75 (PDF), 1,08 (tangkapan layar), 0,97 (foto layar), dan 0,98 (cetakan). Rata-rata Z jujur per penerbitan berkisar dari -0,42 sampai +0,39 pada PDF, -0,93 sampai +0,48 pada tangkapan layar, -0,43 sampai +0,38 pada foto, dan -0,25 sampai +0,49 pada cetakan; simpangan baku antarpenerbitan, setelah bagian di dalam penerbitan dikeluarkan, 0,11 pada PDF, 0,32 pada tangkapan layar, dan sekitar 0 pada foto dan cetakan. Pusat per dokumen pada PDF jauh lebih sempit daripada skema v1 (-1,4 sampai +1,7). Diulang saat peninjauan dengan empat penerbitan lain dan benih baru (`jujur-tinjauan`, nota dinas dan surat telegram, N = 20 dan 100): 0 alarm dari 160 salinan jujur dan 0 dari 12 induk tanpa tanda, simpangan baku Z 0,96, Z terendah -2,40, rata-rata per penerbitan dan kanal -0,65 sampai +0,69. Jadi 0 alarm dari 644 bukti jujur skema v2. Dua belas penerbitan belum cukup untuk menyatakan laju per dokumen; laju 10^-3 tetap hanya berlaku rata-rata atas pembangkitan kode.
* **Serangan** (36 koalisi per kanal, [tabel](#koalisi-yang-memahami-tapak)). Hapus semua yang sama terdeteksi pada 36 dari 36 PDF, 36 dari 36 tangkapan layar, 33 dari 36 foto layar, dan 1 dari 36 cetakan. Median Z per ukuran koalisi 2, 3, dan 4: -17, -25, dan -29 untuk PDF, -10, -16, dan -18 untuk tangkapan layar, -7, -9, dan -15 untuk foto. Cetakan tetap praktis buta, karena kekuatan baca latar yang hanya derau menenggelamkan geser (dari unit geser saja 19 dari 36 cetakan akan ditandai), padahal pada skema v2 cetakan kini membawa cukup geser untuk menyebut salinan jujur. Pembalikan tidak pernah ditandai pada PDF, tangkapan layar, dan foto (median Z +6 sampai +15), dan lolos pada 36 dari 36 di keempat kanal. Koalisi dengan penjangkaran memberi jumlah peringatan dan median Z yang sama (selisih median paling banyak 1).
* **Yang tidak terlihat.** Unit yang dihapus sampai tidak terukur sama sekali (misalnya kelompok kata yang dipotong dari halaman) tidak ikut dalam statistik.

Kekuatan baca latar dari halaman tanpa pola kini tidak dihitung (`research/kontradiksi/`; protokol dan benih baru ditetapkan sebelum dijalankan, ambang tetap Z <= -3,09):

* **Aturannya.** Di cetakan pola latar bawaan tidak sampai ke kertas, tetapi kekuatan baca latarnya yang hanya derau (ribuan posisi) dulu ikut dihitung dan menenggelamkan unit geser. Kini kekuatan baca latar hanya dihitung dari halaman yang pola latarnya ditemukan dekoder, keputusan yang sudah dibuat dekoder tanpa kode penerima (`erasure.SILENT_BACKGROUND_RULE`). Dua bacaan "ditemukan" ditetapkan lebih dulu: keputusan dekoder sendiri, atau salah satu uji kehadiran lolos. Pada benih pengembangan keduanya menandai 24 dari 48 bukti hapus tanpa alarm jujur, jadi seri dimenangkan keputusan dekoder. Protokol tidak membandingkan keduanya dengan perilaku lama, yang pada benih yang sama menandai 35 dari 48 (tetapi tidak satu pun cetakan).
* **Serangan** (benih uji, hapus semua yang sama, 36 koalisi 2 dan 3 salinan per kanal, skema v1 dan v2). Cetakan dua halaman kini ditandai pada 16 dari 36 (sebelumnya 0). Tetapi PDF turun menjadi 29 dari 36 (sebelumnya 36), tangkapan layar 22 dari 36 (36), dan foto 19 dari 36 (31): di bukti itu pola latar yang tersisa sering tidak ditemukan (anggota acak per sel di posisi yang berbeda tidak meninggalkan pola utuh, dan sel yang diratakan membuat taksiran derau dekoder runtuh), padahal kekuatan baca latarnya justru menunjukkan sel yang dihapus. Secara keseluruhan pemeriksaan kini menandai 86 dari 144 bukti hapus, sebelumnya 103 dari 144. Nilai `"semua"` mengembalikan perilaku lama.
* **Bukti jujur.** 0 alarm pada 638 bukti jujur yang cukup terukur (dari 678 pelacakan jujur benih uji, [di bawah](#pemeriksaan-bacaan-jelas-tanpa-nama)), di setiap medium; Z terendah -2,32 (cetakan dua halaman), -1,91 (cetakan satu halaman), -2,18 (foto dengan ISP ponsel), -2,14 (foto monitor), -2,07 (PDF), -1,96 (foto), dan -1,75 (tangkapan layar). Dengan semua kekuatan baca latar, seperti dulu, juga 0 alarm (Z cetakan terendah -2,98).

### Pemeriksaan bacaan jelas tanpa nama

[Batas terbukti](#batas-deteksi-terbukti) berlaku untuk bobot satu bacaan. Bila bacaan cukup jelas sehingga koalisi paling banyak c penerima yang tidak mengubah tanda di tempat salinannya sama hampir pasti tertangkap, tetapi tidak ada salinan yang mencapai ambang, bacaan itu bertentangan dengan dirinya sendiri. Dekoder lalu memberi peringatan (`tapak/decoder/contradiction.py`). Pemeriksaan ini memakai sebaran bias dan bacaan gabungan, tidak pernah kode penerima, dan tidak mengubah ambang, skor, maupun putusan.

* **Aturan.** Setelah tuduhan, semua tahap, dan hanya bila tidak ada nama: B adalah maksimum atas c' = 1 sampai c dari batas peluang tidak satu pun anggota koalisi c' orang mencapai ambang tahap 1 yang dipakai pelacakan itu. Batas itu dihitung dari bobot gabungan dengan plafon laju salah 1 / (1 + exp(0,3 |L|)) ([plafon laju salah](#bit-salah-dan-bobot-lunak)). Peringatan muncul bila B <= 10^-3. Nama tahap lanjutan memerlukan nama tahap 1, jadi "tidak ada nama" sama dengan "tidak ada salinan yang mencapai ambang tahap 1".
* **Yang dibuktikan.** Untuk bukti jujur, yaitu koalisi paling banyak c yang mematuhi asumsi penandaan (termasuk satu pembocor), peluang peringatan paling besar 10^-3: P(peringatan) = E[1{B <= 10^-3} P(tidak ada anggota mencapai ambang | |L|)] <= 10^-3, karena batasnya berlaku bersyarat pada |L| bacaan dan B hanya fungsi |L| (bobot dan plafonnya keduanya dihitung dari |L|). Peluang ini atas undian kode rahasia dokumen, strategi koalisi, dan derau bacaan, seperti batas deteksi: untuk satu dokumen dan satu koalisi tertentu lajunya dapat lebih besar, sedangkan rata-ratanya atas dokumen tetap paling besar 10^-3. Laju 10^-3 ditetapkan sebelum pengukuran, sama dengan pemeriksaan pola penghapusan.
* **Yang diperlukan.** Kedua syarat batas: derau bacaan tidak bergantung pada kode, dan dengan bobot diketahui bit salah saling bebas dengan laju paling besar plafonnya. Strategi yang menghapus atau melemahkan tanda di posisi tempat salinan berbeda (rata-rata salinan) membuat bobot bergantung pada kode, jadi tidak tercakup bukti ini dan hanya diukur. Plafonnya diukur pada 30 salinan jujur dari 3 penerbitan pengembangan lewat 7 medium: PDF tidak pernah salah, foto dan tangkapan layar mendekati terkalibrasi di bawah |L| = 4 dan terlalu yakin di atasnya (tangkapan layar: 35 salah dari 51.154 posisi dengan |L| >= 12, perkiraan terkalibrasinya 0,3), dan cetakan paling buruk (26 salah dari 2.741 posisi dengan |L| >= 12, sekitar 1 %, kebanyakan seluruh baris yang terbaca dengan offset salah). Faktor peredam terbesar yang menutupi semua medium dan kelompok |L| dengan aturan yang ditetapkan lebih dulu adalah 0,3, jadi tanda PDF yang terbaca dengan |L| = 12 dianggap salah dengan peluang 2,7 %. Akibatnya pemeriksaan praktis hanya dapat berbunyi pada PDF dan tangkapan layar yang jelas: pada salinan jujur benih uji (salinan 1 sampai 5 setiap penerbitan) median B 10^-21,5 untuk PDF, 10^-4,7 untuk tangkapan layar, 10^-0,7 untuk foto dasar, dan 1 untuk foto dengan ISP ponsel, foto monitor, dan cetakan.
* **Biaya.** Batas dihitung pada paling banyak 64 kotak bobot, mulai dari koalisi terbesar, dan berhenti begitu satu ukuran koalisi di atas 10^-3. Terukur di mesin uji yang dipakai bersama: median 0,28 detik dan persentil 95 0,58 detik per bukti (2.424 pelacakan benih uji, diukur juga bila ada nama), dan median 0,25 detik pada 1.408 bukti tanpa nama, satu-satunya saat pemeriksaan berjalan. Pembacaan bukti sendiri lebih lama: diukur saat peninjauan di mesin yang sama, sekitar 2 sampai 3 detik untuk PDF 2 halaman dan 3 sampai 15 detik untuk tangkapan layar atau foto.
* **Tampilan.** Halaman Lacak, CLI, JSON, dan berita acara menulis di bawah putusan: "bukti terbaca jelas, tetapi tidak ada salinan yang mencapai ambang", dengan batasnya, kemungkinan penyebab (tanda dibalik atau diacak oleh orang yang memahami TAPAK, misalnya koalisi pemegang dua salinan atau lebih; koalisi lebih dari c orang; atau masalah pembacaan bukti), dan bahwa tidak ada nama yang disebut karenanya. Bila pemeriksaan pola penghapusan juga memberi peringatan, keduanya menjadi satu peringatan dengan satu kalimat penutup. Nilai batasnya selalu dicatat bila pemeriksaan berjalan (kotak keabsahan di halaman Lacak, JSON, berita acara).

Terukur pada benih uji (`research/kontradiksi/`; protokol, benih, dan analisis ditetapkan sebelum dijalankan; pelacakan pertama yang tercatat, bertahap):

* **Bukti jujur.** Tidak ada peringatan pada 678 pelacakan jujur: salinan 1 sampai 5 dan koalisi 2 dan 3 salinan dengan lima strategi standar (anggota acak, salinan pertama, rata-rata, mayoritas, minoritas) dari 6 penerbitan (nota dinas dan surat telegram, N = 20 dan 100, skema v1 dan v2) lewat 7 medium (PDF, tangkapan layar, foto dasar, foto dengan ISP ponsel, foto monitor, foto cetakan satu dan dua halaman), penerbitan dengan profil latar cetak lewat PDF dan cetakan, induk hasil pindai lewat PDF, foto, dan cetakan (salinan saja; koalisinya tidak dapat dipalsukan dengan kode riset), serta 18 induk tanpa tanda. Peringatan hanya mungkin bila tidak ada nama. Dari 177 bukti tanpa nama (kebanyakan cetakan: 75 dari 97 satu halaman dan 69 dari 100 dua halaman; juga 7 foto, 7 foto monitor, 1 foto ISP, dan 18 induk) tidak satu pun batasnya di bawah 1, juga dengan laju terkalibrasi tanpa peredam. Setiap penerbitan 0 peringatan (20 sampai 36 bukti tanpa nama di setiap penerbitan dengan profil latar bawaan; penerbitan profil latar cetak dan induk hasil pindai menyebut nama pada semua buktinya). Diulang saat peninjauan dengan benih baru (9301, nota dinas, N = 20, skema v2: salinan 1 sampai 10 dan tiga koalisi standar lewat cetakan satu dan dua halaman dan foto monitor): 0 peringatan dari 39 pelacakan, 8 tanpa nama, semuanya dengan batas 1. Nol dari 678 hanya menunjukkan lajunya di bawah sekitar 4 x 10^-3; batas 10^-3 datang dari bukti di atas, dengan syaratnya. Tidak ada tuduhan salah.
* **Koalisi yang memahami TAPAK** (36 koalisi 2 dan 3 salinan per kanal, skema v1 dan v2, N = 20 dan 100). Pembalikan tanda di posisi yang sama pada PDF yang diteruskan kini diberi peringatan pada 36 dari 36 bukti (batas paling besar 6 x 10^-7, median 4 x 10^-9), dan satu salinan yang membalik semua tandanya sendiri pada 18 dari 18. Selebihnya koalisi tetap lolos tanpa peringatan ini:
  * pembalikan yang diteruskan sebagai tangkapan layar, foto, atau cetakan (0 dari 36 di setiap kanal): dekoder latar foto menaksir penguatannya dari posisi pilot, yang hampir selalu posisi yang sama, jadi pola yang dibalik dibaca sebagai "tidak ada pola" (ditemukan pada 0, 5, dan 1 dari 36), dan sisa bukti, sekitar 220 posisi geser, terlalu sedikit untuk jaminan terhadap 3 anggota;
  * tanda yang diacak di posisi yang sama, dengan tanda acak per sel karena koalisi tidak tahu sel mana yang satu posisi: pola latar tidak utuh lagi dan bobotnya kecil (0 peringatan; pemeriksaan pola penghapusan menandai 13 dari 36 PDF dan 3 dari 36 tangkapan layar);
  * pembalikan sebagian: varian adaptif dengan kode dan dekoder sungguhan sebagai orakel (lebih kuat dari koalisi mana pun) membalik bagian terkecil yang membuat tidak satu pun anggota disebut pada PDF, 40 sampai 45 % sel dan unit. Sel satu posisi lalu hanya sebagian dibalik, jadi setiap posisi latar melemah, bukan terbalik (0 peringatan; pola penghapusan 6 dari 36 PDF);
  * seluruh pola latar dibuang lalu geser yang sama dibalik: 0 peringatan dari kedua pemeriksaan pada PDF, tangkapan layar, dan foto (cetakan tidak diuji); yang tersisa hanya kanal geser (median 246 posisi pada PDF, sekitar 220 pada gambar).

  Tidak ada tuduhan salah di 846 pelacakan bukti yang diserang.
* **Harga bagi koalisi** (16 koalisi 2 dan 3 salinan, skema v2, pembalikan dan varian adaptif ditambah degradasi yang tidak bergantung pada kode sampai peringatan berhenti). Pada PDF yang dibalik, peringatan berhenti begitu derau Gauss dengan simpangan baku 3 tingkat abu-abu (11 koalisi) atau 4 tingkat (5 koalisi) ditambahkan ke gambar pola latar, yang amplitudonya 2 tingkat. Di titik itu bukti masih membawa 97 sampai 99 % posisi kode (2.908 sampai 3.226; jumlah w^2 2.392 sampai 2.849), tidak ada anggota yang disebut, dan salinan jujur dengan derau yang sama disebut pada 16 dari 16. Salinan jujur itu masih membawa kanal teks, yang dibuang setiap serangan; diperiksa sesudahnya tanpa kanal teks (`tambahan.py`, di luar protokol), salinan jujur tetap disebut pada 16 dari 16 dengan derau 3 dan 4 (batas median 10^-8,7 dan 10^-4,4), juga bila seluruh pola latar dibuang. Lewat gambar (PNG, JPEG 90 sampai 50, blur, 1.200 piksel, foto) peringatan tidak pernah muncul pada 192 bukti yang dibalik atau dibalik sebagian, sedangkan salinan jujur disebut di setiap tingkat (16 dari 16). Varian adaptif tidak pernah diberi peringatan, juga tanpa degradasi (240 bukti). Jadi menghindari peringatan ini hampir tanpa biaya bagi koalisi: buktinya tetap sejelas yang cukup untuk menyebut salinan jujur. Saat peninjauan (benih baru 9301, di luar protokol) bahkan satu salinan cukup: membuang gambar pola latar setiap halaman dan mencerminkan semua unit geser salinan itu sendiri lolos dari kedua pemeriksaan tanpa nama, pada PDF (439 posisi geser tersisa) maupun tangkapan layar (243), dan PDF yang dibalik dengan derau 4 tingkat lolos dengan 2.924 posisi terbaca, sedangkan salinan jujur dengan derau yang sama disebut.
* **Koalisi lebih dari c** (4 penerbitan skema v2, N = 20 dan 100, koalisi jujur 4, 5, dan 6 salinan dengan lima strategi standar lewat PDF, tangkapan layar, dan foto; 180 pelacakan). Ini salah satu penyebab yang disebut peringatan itu, jadi peringatan di sini memang diharapkan. PDF selalu menyebut paling sedikit satu anggota. Dari 41 bukti tanpa nama, semuanya tangkapan layar dan foto, 12 diberi peringatan: 0 dari 6 untuk 4 orang, 3 dari 15 untuk 5 orang, dan 9 dari 20 untuk 6 orang, kebanyakan dengan strategi mayoritas (8) dan rata-rata (3); batasnya 10^-5,9 sampai 10^-3,1. Tidak ada tuduhan salah, dan pemeriksaan pola penghapusan tidak berbunyi.
* **Yang tidak terlihat.** Semua yang menurunkan bobot: penghapusan (diperiksa pemeriksaan pola penghapusan), kanal yang dibuang seluruhnya, pola latar yang dibaca dekoder foto sebagai "tidak ada pola", dan degradasi yang menyisakan terlalu sedikit posisi jelas untuk jaminan terhadap c anggota. Batasnya lalu besar dan pemeriksaan diam.

### Penyamaran per salinan (diuji, tidak dipakai)

Penyamaran membuat salinan berbeda di setiap posisi, sehingga kesamaan tidak terlihat dengan membandingkan salinan. Skema `samaran-latar-v1` (`research/sepakat/samaran.py`) menambahkan ke setiap sel latar topeng berkunci per salinan, dari kunci yang diturunkan dari rahasia kode dan id salinan, jadi tidak bergantung pada kode mana pun. Topeng saling meniadakan di dalam delapan sel satu posisi, sehingga rata-rata terurai yang dibaca dekoder tidak berubah. Dekoder tidak diubah dan menganggap topeng sebagai derau; topeng tidak pernah dikurangkan per salinan kandidat, karena itu akan merusak batas tuduhan salah. Dua kandidat ditetapkan sebelum pengukuran: K1 (amplitudo 1, topeng +/-1,5, tingkat 250 sampai 255, jadi tidak tercetak) dan K2 (amplitudo 2, topeng +/-2, tingkat 243 sampai 255).

* **Tampilan.** K1 lolos: S-CIELAB pada 35 cm rata-rata 0,28 dan persentil 95 sebesar 0,57 di layar (pola sekarang 0,42 dan 0,77), di kertas sama dengan sekarang. K2 tidak lolos di kertas (1,02 dan 2,16; batasnya 0,75 dan 2,0). Geser tidak diubah, jadi batas 0,10 mm antara dua salinan tetap berlaku.
* **Harga untuk bukti jujur** (K1, foto dan benih benchmark README yang sama, saat penerbitannya masih skema v1): 39 dari 40 foto layar, 0 dari 16 cetak satu halaman, 8 dari 8 dua halaman, sama dengan tanpa topeng. Sinyalnya separuh: galat bit latar pada foto layar naik dari median 0,9 % menjadi 11 %, dan skor salinan yang benar turun menjadi sekitar 0,82 kali skor sekarang. Pada foto salinan pertama di set uji, K1 benar 57 dari 60 (sekarang 58).
* **Yang masih dapat dilakukan koalisi.** Koalisi tidak perlu menebak dengan tepat; menghapus lebih banyak tidak merugikannya. Dengan nilai sel yang dibaca kontinu dan aturan Bayes, koalisi meratakan hampir semua sel di posisi yang sama (99,98 % dengan dua salinan) dan sebagian besar sel di posisi yang berbeda (62 %). Dengan 3 dan 4 salinan, perbandingannya lebih tepat, sehingga perataan sel berbeda turun menjadi 44 dan 33 % (perhitungan tingkat sel, `samaran.py` bagian `abstrak`). Pada set uji, hapus semua yang sama tetap lolos pada 60 dari 60 bukti PDF, tangkapan layar, dan foto, sama dengan tanpa penyamaran; yang turun hanya deteksinya (PDF 60, tangkapan layar 48, foto 25 dari 60), karena penghapusannya kini lebih merata.
* **Keputusan.** Aturan yang ditetapkan sebelum pengukuran (`research/sepakat/ukur.py`): menjadi bawaan hanya bila hasil benchmark tetap dalam selisih 1 salinan, lolos uji tampilan, dan laju lolos turun sedikitnya separuh dan 25 poin persentase; menjadi pilihan bila dua syarat terakhir terpenuhi. K1 memenuhi dua syarat pertama, tetapi laju lolos tidak turun sama sekali, jadi penyamaran tidak dipakai, juga tidak sebagai pilihan. Penerbitan tidak berubah, dan hasil benchmark README dengan dekoder saat itu sama byte demi byte dengan sebelumnya.
* **Geser tidak disamarkan.** Satu salinan sudah mengungkap arah geser lewat tipografi sama tepatnya dengan dekoder membacanya. Jitter per salinan yang cukup besar untuk menyamarkan kesamaan akan menambah derau yang sama pada bacaan dekoder, dan batas 0,10 mm tidak menyisakan ruang: kelompok data skema v1 sudah bergeser 0,05 mm, dan pada skema v2 celah kata sudah berubah sampai 0,05 mm, batas yang sama dengan v1.

## Hasil lain

| Pengujian | Hasil |
|---|---|
| Kumpulan foto sintetis (`make photos` lalu `make bench`): 32 foto layar bersudut 0 sampai 30 derajat dan 8 tangkapan layar dari 4 salinan (halaman 1), dikompresi JPEG dua kali seperti WhatsApp. Satu penerbitan 20 salinan dengan skema geser bawaan v2; rahasia kode dan id salinan dari benih riset 2026, benih foto 2026, jadi hasilnya terulang persis ([operasi](operasi.md#benchmark-foto)) | 40 dari 40 benar, 0 tuduhan salah. Foto dengan 95 % kertas jenuh putih (pola latar terhapus) disebut lewat kanal geser saja, dengan skor tipis di atas ambang (batas peluang tuduhan salah 9,3 x 10^-7); 39 lainnya paling besar 4,0 x 10^-26. Dua foto dengan 88 dan 90 % kertas jenuh gagal dengan dekoder latar lama dan kini benar ([batasan 4](keamanan.md#batasan)). Skema v1 (benchmark sebelumnya): 39 dari 40, foto 95 % itu "tidak cukup bukti" |
| Foto kertas cetak (`make photos-cetak` lalu `make bench`, dilaporkan terpisah): halaman 1 dan 2 dari 4 salinan yang sama, dicetak printer laser simulasi dengan profil latar bawaan, 16 foto (10 dan 30 derajat, 1600 px) dan 8 pasangan dua halaman | satu halaman 9 dari 16 benar (halaman 1: 8 dari 8; halaman 2, yang lebih pendek: 1 dari 8), dua halaman 8 dari 8, 0 tuduhan salah; batas peluang tuduhan salah paling besar 5,3 x 10^-7 (satu halaman) dan 2,2 x 10^-11 (dua halaman). Skema v1: satu halaman 0 dari 16, dua halaman 8 dari 8 dengan skor hanya 1,02 sampai 1,19 kali ambang. Satu rahasia kode dan printer simulasi; dengan rahasia lain angkanya dapat lebih rendah ([batasan 3](keamanan.md#batasan)) |
| Foto ponsel dan foto layar simulasi (`make photos-ponsel`, `make photos-layar`, dilaporkan terpisah; [rincian](#foto-ponsel-dan-foto-layar-simulasi)): adegan `make photos` lewat ISP ponsel, dan salinan di monitor simulasi 93 sampai 227 ppi dengan ISP ponsel, 32 foto masing-masing dari 4 salinan yang sama (halaman 1, 0 sampai 30 derajat) | ISP ponsel 32 dari 32 benar, monitor 32 dari 32, 0 tuduhan salah; batas peluang tuduhan salah paling besar 1,2 x 10^-41 dan 7,3 x 10^-8. Yang terlemah adalah laptop 13 inci dari 45 cm (halaman mengisi 26 % bingkai), yang gagal dengan skema v1 (monitor 31 dari 32) |
| Tangkapan layar yang digambar MuPDF, Poppler Splash, dan Poppler Cairo pada 28 sampai 150 dpi, PNG, lewat aplikasi pesan, dan diperkecil (kedua dokumen contoh, N = 20, set uji tertahan, 2.250 gambar; [rincian](#tangkapan-layar-dari-penampil-pdf)) | Halaman utuh disebut sampai 28 sampai 40 dpi (Splash tanpa anti-aliasing 48 sampai 56 dpi), lewat pola latar; kanal geser saja dari 72 sampai 120 dpi (tidak pernah pada tangkapan Poppler yang diperkecil dan pada Splash tanpa anti-aliasing). Model kisi baris: bit baris salah yakin 470 menjadi 243, putusan geser saja 516 menjadi 542. 0 tuduhan salah dalam 2.346 pelacakan |
| 10 foto sintetis bersudut sampai 30 derajat | 10 dari 10 benar |
| Halaman gabungan digital: setengah atas salinan A, setengah bawah salinan B (2 pasangan) | penerima A dan B dituduh, tidak ada orang lain |
| Teks salinan disalin-tempel (MuPDF dan poppler) | kode utuh, salinan teridentifikasi |
| Teks diketik ulang dengan 5 % salah ketik (kanal semantik) | 4 bit semantik pulih 20 dari 20 percobaan; tidak cukup untuk menyebut nama |
| Teks diketik ulang, kanal pilihan kata ([rincian](#kanal-pilihan-kata-opsional)): dokumen sintetis 6 halaman (47 bit), 200 percobaan untuk N = 20 dan 200 untuk N = 100, pelacakan pertama yang tercatat | 395 dari 400 benar, 0 tuduhan salah; nota dinas contoh 2 halaman (11 bit): "tidak cukup bukti" |
| Varian kalimat dan pilihan kata dibaca dengan OCR dari foto, tangkapan layar, dan foto cetak sintetis (kedua dokumen contoh, N = 20, set uji tertahan; [rincian](#teks-terlihat-pada-bukti-gambar-ocr)) | 1.765 dari 1.771 bit yang tercetak terbaca, 0 salah; 27 putusan foto cetak berubah menjadi benar, tidak satu pun sebaliknya; 0 tuduhan salah dalam 598 pelacakan |
| Dokumen induk hasil pindai (nota dinas sintetis 2 halaman, 300 dpi), 20 salinan: PDF salinan, tangkapan layar, dan foto sintetis halaman 1 ([rincian](keamanan.md#batasan)) | 60 dari 60 benar, 0 tuduhan salah; gabungan sepertiga halaman dari 3 salinan: 15 dari 15 anggota koalisi tertangkap, tidak ada orang lain |
| Penerbitan 20 salinan dokumen 2 halaman | sekitar 4 sampai 5 detik (hasil pindai 300 dpi: sekitar 30 detik) |
| Kanari DNS, pembukaan disimulasikan (kueri langsung ke pendengar lokal) | tercatat dalam sekitar 0,1 detik (syarat: di bawah 5 detik) |
| Registri: verifikasi hanya dengan kunci publik, setiap perubahan baris terdeteksi | lulus |
| `make demo` (skenario lengkap) | sekitar 18 sampai 20 detik di mesin uji yang dipakai bersama, termasuk sekitar 5 detik untuk templat induk tepat pada pelacakan foto; sejak varian kalimat pada foto dibaca dengan OCR, sekitar 3 detik lebih lama |

## Kanal pilihan kata (opsional)

Pengetikan ulang menghapus semua tanda kecuali isi kata-katanya. Kanal ini memberi setiap salinan pilihannya sendiri di antara bentuk yang bermakna sama dalam naskah dinas, misalnya "sehubungan dengan" atau "berkenaan dengan", "terdiri atas" atau "terdiri dari", "dan" atau "serta" di antara dua kata biasa. Kanal ini tidak aktif kecuali penerbit memilihnya dan meninjau setiap titiknya (`tapak leksikal` atau halaman Terbitkan, lihat [operasi](operasi.md#kanal-pilihan-kata-opsional)). Tanpa itu, penerbitan, catatan penerbitan, dan registri sama persis dengan sebelumnya.

* **Tabel leksikon.** Bentuk-bentuknya ada di `tapak/assets/leksikon/naskah_dinas_v1.json` (versi 1). Tabel ini masih **draf** dan belum disahkan peninjau bahasa Tata Naskah Dinas. Versi dan digest tabel dicatat di berkas tinjauan, catatan penerbitan, dan registri. Bentuk dalam satu aturan berbeda sedikitnya 3 karakter, dan tidak ada bentuk yang sama dengan bentuk lain dikurangi satu kata. Dengan begitu, salah ketik atau kata yang terlewat tidak mengubah satu bentuk menjadi bentuk lain.
* **Yang tidak pernah diubah.** Angka, nama, satuan, jabatan, waktu, koordinat, bilangan, perintah, larangan, tenggat, dan kata ingkar tidak pernah diubah. Frasa ditolak bila frasa itu sendiri, atau kata dalam jarak dua kata di kalimat yang sama, termasuk salah satunya. Ungkapan tetap seperti "dan lain-lain", "namun demikian", atau "untuk mereka" juga ditolak. Judul paragraf (juga "14. Maksud dan tujuan."), kepala surat, tanda tangan, tembusan, kaki halaman, dan kalimat kanal semantik tidak disentuh; tanda tangan, tembusan, dan kaki halaman juga tidak dihitung sebagai kata isi. Pemindaian hanya melaporkan jumlah penolakan per kategori, tanpa kata dokumen.
* **Tata letak.** Setiap kombinasi bentuk pada satu baris harus muat kembali di baris yang sama: tepi kiri dan kanan tetap, label "1.", "14." atau "a." dan kata pertama sesudahnya tetap di tempatnya (label dikenali dari bentuknya dan kolom teksnya, bukan dari lebar celahnya), jarak antarkata 1 sampai 3 spasi. Kata lain di baris itu digambar dengan glifnya sendiri dan tetap membawa karakter tak terlihat serta huruf kembarnya. Baris itu keluar dari kanal geser. Pada nota dinas contoh dengan skema geser v1, kanal geser turun dari 183 menjadi 140 bit; pada surat telegram, dari 97 menjadi 84.
* **Peninjauan.** Setiap titik disetujui atau ditolak manusia, dengan melihat seluruh kalimatnya (lintas baris) dan frasanya dalam kurung siku. Penerbitan diblokir selama masih ada titik yang menunggu. Titik dan bentuk yang disunting di luar TAPAK ditolak, karena digest pemindaiannya tidak cocok dan pemindaian ulang dokumen induk memberi titik yang berbeda. Keputusan setuju atau tolak di berkas itu tidak diautentikasi: berkas yang statusnya disunting tangan tetap diterima, jadi `leksikal.json` dijaga seperti dokumen induk.
* **Posisi kode.** Dokumen yang memakai kanal ini mengambil posisi kanal semantik dan pilihan kata hanya dari posisi dengan bias 0,3 sampai 0,7. Keduanya memakai satu urutan berkunci: semantik dari depan, pilihan kata dari belakang. Penerbitan ditolak bila pita itu tidak cukup untuk semua bit keduanya (misalnya c = 1 dengan dokumen panjang), jadi posisinya tidak pernah bertabrakan atau berulang. Aturan ini dicatat sebagai `retype_positions` di catatan penerbitan dan registri; dokumen lama tetap memakai aturan seragam. Pemilihan hanya memakai vektor bias, tidak pernah kode penerima, jadi ambang Chernoff tetap berlaku. Di dekat p = 1/2, satu pembocor menyumbang skor sampai 1 per bit. Sebaliknya, koalisi yang memilih bit minoritas menekan skornya ke sekitar nol, jadi posisi ini hanya menolong untuk pembocor tunggal.
* **Dekode.** Teks bukti disejajarkan dengan teks induk (jarak edit), lalu setiap bentuk dicocokkan bersama konteks 16 karakter di kiri dan kanannya. LLR = 2 x selisih jarak edit, paling besar 6, dan paling besar 2 bila suntingan berkumpul di frasa itu. Frasa yang ditulis ulang atau terpotong dianggap tidak terbaca, bukan dibaca salah. Pengecualiannya titik berkonteks berulang: frasa dan konteksnya juga ada di bagian lain dokumen. Bila pembocor menukar urutan kalimat, titik itu dapat terbaca di tempat lain dengan yakin. Akibatnya skor pembocor turun, tetapi salinan lain tidak pernah tertuduh karenanya. Pemindaian menandai titik seperti ini untuk peninjau; kedua contoh tidak memilikinya. Ambangnya tetap dihitung dari vektor bias dan bobot dekoder.
* **Tanda yang terlihat.** Pilihan kata dan varian kalimat terlihat di kertas. Bila sebuah nama hanya didukung kedua kanal itu (tanpa keduanya salinan itu tidak mencapai ambang), juga bila keduanya dibaca dengan [OCR](#teks-terlihat-pada-bukti-gambar-ocr) dari foto atau cetakan, hasil CLI, web, dan berita acara menambahkan peringatan di bawah putusan: siapa pun yang pernah membaca salinan itu dapat meniru pilihan katanya saat mengetik ulang, jadi hasil itu menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan memerlukan bukti pendukung. Peringatan ini tidak mengubah ambang atau putusan.

Angka di bawah dibuat ulang dengan `research/ketik/ukur.py`; semua pilihan acak berasal dari benih tetap, dan keluarannya disimpan di `research/ketik/hasil/` (`kapasitas.jsonl`, `galat.jsonl`, `atribusi.jsonl`). Pengetikan ulangnya disimulasikan (`tapak/ketik.py`); belum ada orang sungguhan yang mengetik ulang. Semua angka memakai tabel draf tingkat A.

Kapasitas. Dokumen sintetis panjang berisi paragraf isi kedua templat contoh yang diulang 2 sampai 6 kali. Karena paragrafnya berulang, semua titiknya berkonteks berulang: angka atribusi di bawah berlaku untuk bocoran yang tidak menukar urutan kalimat.

| Dokumen | Halaman | Kata isi | Bit pilihan kata |
|---|---|---|---|
| nota dinas contoh | 2 | 307 | 11 |
| surat telegram contoh | 2 (isi 1 halaman) | 137 | 5 |
| sintetis | 4 / 6 / 7 / 8 / 10 | 883 / 1.318 / 1.757 / 2.201 / 2.641 | 31 / 47 / 62 / 78 / 94 |

Rata-ratanya sekitar 3,6 bit per 100 kata isi, atau sekitar 10 bit per halaman isi penuh (sekitar 290 kata).

Galat baca, 500 salinan per dokumen per tingkat derau. Setiap salinan memakai rahasia kode baru, dan setiap sel berisi bit terhapus lalu bit salah di antara yang terbaca. Tingkat "sedang" berarti per kata 5 % salah ketik, 1 % salah baca OCR, 1 % kata hilang, 1 % kata menyatu, dan 5 % tanda baca hilang. "Kebiasaan" berarti pengetik menulis bentuk induk, bukan bentuk salinannya, pada 5 % titik; galat ini sistematis dan tidak terlihat dekoder.

| Derau | nota dinas (5.500 bit) | surat telegram (2.500 bit) | sintetis 6 halaman (23.500 bit) |
|---|---|---|---|
| tanpa derau | 0 %; 0 salah | 0 %; 0 salah | 0 %; 0 salah |
| ringan | 0,7 %; 0,13 % | 0,5 %; 0,48 % | 0,6 %; 0,19 % |
| sedang | 1,3 %; 0,24 % (13 dari 5.428) | 0,8 %; 0,60 % (15 dari 2.480) | 1,3 %; 0,41 % (95 dari 23.206) |
| berat | 4,7 %; 0,63 % | 3,3 %; 2,3 % | 4,1 %; 1,1 % |
| OCR | 0,7 %; 0,13 % | 0,6 %; 0,32 % | 0,6 %; 0,21 % |
| sedang + kebiasaan 5 % | 1,3 %; 2,6 % | 1,0 %; 2,9 % | 1,3 %; 2,9 % |

Atribusi pembocor tunggal, 200 percobaan per sel. Teks salinan diketik ulang pada tingkat sedang dan dibaca dekoder. Putusannya dari `fuse` dan `attribute` dengan jatah eps pelacakan pertama yang tercatat di registri (61 % dari eps = 10^-6), memakai bit pilihan kata saja (tanpa bit semantik).

| Dokumen | Kata isi | Bit | Disebut benar, N = 20 | Disebut benar, N = 100 |
|---|---|---|---|---|
| nota dinas contoh | 307 | 11 | 0 dari 200 | 0 dari 200 |
| sintetis 4 halaman | 883 | 31 | 12 dari 200 | 1 dari 200 |
| sintetis 6 halaman | 1.318 | 47 | 200 dari 200 | 195 dari 200 |
| sintetis 7 halaman | 1.757 | 62 | 200 dari 200 | 200 dari 200 |
| sintetis 8 halaman | 2.201 | 78 | 200 dari 200 | 200 dari 200 |

Tidak ada tuduhan salah dalam 2.000 percobaan. Ada dua angka yang berbeda:

* **Terukur.** Pada derau sedang, deteksi 95 % tercapai di antara 883 kata isi (31 bit) dan 1.318 kata isi (47 bit), kira-kira mulai 1.300 kata isi atau 4 sampai 5 halaman isi penuh. Pelacakan berikutnya memakai jatah eps yang lebih kecil, jadi deteksinya sedikit turun.
* **Batas TAPAK.** Keluaran penerbit baru menyatakan "cukup untuk satu pembocor" mulai 64 bit (bit semantik ikut dihitung), sekitar 1.800 kata isi atau 6 halaman isi penuh dengan tabel ini. Batas ini ditetapkan sebelum pengukuran di atas, dengan cadangan untuk derau berat dan kebiasaan pengetik: simulasi riset menunjukkan 56 sampai 64 bit untuk deteksi 95 % pada kondisi itu. Di bawahnya, penerbit dan berita acara menyebut kekurangan bitnya dan perkiraan kata isi tambahan menurut kepadatan dokumen itu sendiri.

Kolusi tidak tertangani di teks ketikan ulang. Menurut simulasi riset (200 percobaan per sel, derau baca terukur), koalisi 3 orang yang memilih bentuk minoritas tidak pernah tertangkap dengan posisi pita (0 dari 200 sampai 768 bit). Dengan posisi seragam pun koalisi itu baru tertangkap pada sekitar 1.000 sampai 1.500 bit, kira-kira 90 sampai 140 halaman isi dengan tabel ini.

## Teks terlihat pada bukti gambar (OCR)

Varian kalimat dan pilihan kata adalah kata yang tercetak di halaman. Keduanya bertahan pada foto, tangkapan layar, pindaian, dan cetakan, sedangkan pola latar bawaan tidak sampai ke kertas. Karena itu, bila dokumen memakai salah satu kanal itu, halaman yang ditemukan pada bukti gambar juga dibaca teksnya dengan Tesseract lokal (`tapak/decoder/ocr.py`). Dokumen tanpa kedua kanal itu dilacak persis seperti sebelumnya; penerbitan benchmark README tidak memakainya, jadi hasilnya tidak berubah.

* **Pembacaan.** Registrasi menemukan halaman induk dan meluruskan gambar ke bingkai halaman itu (urutan halaman dan potongan yang sama dengan kanal geser dan latar). Halaman terektifikasi dibagi taksiran terang kertasnya, sehingga bayangan, vinyet, dan pencahayaan tidak rata hilang, lalu dibaca Tesseract (`-l ind+eng --oem 1 --psm 3`, satu utas, resolusi analisis registrasi). Gambar masuk lewat stdin dan teks keluar lewat stdout, tanpa berkas sementara. Halaman yang tidak memuat slot kedua kanal tidak dibaca.
* **Pembaca yang sama.** Teksnya hanya diberikan ke pembaca varian kalimat dan pilihan kata yang dipakai untuk teks tempelan, tanpa perubahan, dan hanya untuk slot yang tercetak di halaman itu. Acuan pilihan kata hanya memuat baris halaman itu, jadi konteks sebuah titik berakhir di tepi halaman, seperti pada gambar. Keduanya tetap buta kode: hanya halaman, slot, teks induk, dan himpunan varian yang dipakai, tidak pernah kode penerima.
* **Tidak ke kanal teks.** Teks OCR tidak pernah diberikan ke kanal karakter tak terlihat dan huruf kembar. OCR tidak melihat simbol lebar-nol dan membaca huruf kembar sebagai huruf Latin biasa, jadi keluarannya tidak berkata apa pun tentang tanda itu.
* **Teks rusak menjadi terhapus.** Pembaca menolak kalimat atau titik yang bentuk terdekatnya terlalu jauh dari teks, atau yang penjajarannya menunjukkan suntingan rapat di frasa itu (terpotong, ditulis ulang, atau tak terbaca), dan memberi LLR rendah pada suntingan yang berkumpul. Galat ini diukur pada keluaran OCR sungguhan dari gambar sintetis, bukan pada salah ketik simulasi: pada set uji tertahan tidak satu pun dari 1.765 bit yang terbaca salah; empat kalimat atau titik terhapus dan tiga dibaca dengan keyakinan rendah.
* **Label, bukan teks.** Sub-kanalnya `semantic_ocr` dan `lexical_ocr`, bagian dari kanal fisik semantik dan leksikal. CLI, JSON, halaman Lacak, dan berita acara menulis kanal itu dengan keterangan "OCR gambar" (atau "teks dan OCR gambar" bila juga dibaca dari teks), dan tidak pernah menampilkan teks OCR. Diagnostik hanya memuat jumlah, id kalimat dan titik, halaman, dan waktu OCR. Nama yang hanya didukung tanda ini tetap diberi [peringatan tanda yang terlihat](#kanal-pilihan-kata-opsional).
* **Foto terpotong.** Kalimat atau titik yang kata tercetaknya tidak seluruhnya ada di dalam gambar tidak dibaca (hanya geometri registrasi yang menentukan), dan hasil menyebut jumlahnya ("tanda di luar gambar, tidak dibaca"). Frasa yang terpotong tepi gambar kalau dibaca akan memenangkan bentuk yang lebih pendek.
* **Kata yang ditimpa atau dipalsukan.** OCR membaca kata yang terlihat. Bentuk lain yang diketik di atas bentuk tercetak kadang terbaca sebagai bentuk itu, dan bentuk palsu di atas penghapus selalu terbaca sebagai bentuk palsu. Pada pemeriksaan tinjauan dengan benih baru (`research/ocr/README.md`), foto buram, kecil, terbalik, terpotong, dan sangat terkompresi tidak memberi satu pun bit salah, tetapi penimpaan tanpa penghapus memberi 8 bit salah dari 40 yang terbaca, 2 di antaranya dengan yakin. Ini batas yang sama dengan pengetikan ulang: siapa pun yang melihat bentuk salinan lain dapat menuliskannya, jadi nama yang hanya didukung tanda ini tetap diberi peringatan dan memerlukan bukti pendukung.
* **Bukti yang sama dua kali.** PDF dan foto salinan yang sama, atau dua foto halaman yang sama, membaca frasa yang sama. Frasa itu dihitung sebagai satu tanda ([fusi bukti](#fusi-bukti)).
* **Tanpa Tesseract** (atau tanpa data bahasa Indonesia), pelacakan tetap berjalan tanpa kedua sub-kanal itu, dan hasilnya menyebutnya dalam satu baris catatan.
* **Waktu.** Tesseract memerlukan median 2,9 detik per halaman di mesin uji yang dipakai bersama (gambar 1600 px sekitar 2,7 detik, foto cetak 4000 px 4,3 detik, paling lama 9,8 detik), di atas dekode kanal geser dan latar. Pada halaman penuh seluruh langkah OCR (termasuk perataan terang dan kedua pembaca) menambah sekitar 2,4 detik pada foto 1600 px dan 4,5 sampai 5 detik pada foto cetak 4000 px, yang tanpa OCR memerlukan 3,6 dan 43 detik.

**Pemilihan pengaturan.** Protokol, benih, kandidat, dan aturan pemilihan ditetapkan di `research/ocr/ukur.py` sebelum pengukuran ([rinciannya](../research/ocr/README.md)). Pada 96 gambar pengembangan (kedua dokumen contoh, salinan 1 sampai 6, enam jenis bukti), psm 3 pada halaman yang dibagi terang kertasnya membaca 778 dari 780 bit yang tercetak, tanpa satu pun yang salah. Tanpa pembagian itu psm 3 membaca 701, psm 4 721, psm 6 738, dan pencuplikan ulang ke 300 dpi 709 (psm 3) dan 728 dengan satu bit salah (psm 6), dengan waktu OCR sekitar 1,6 kali lebih lama.

**Hasil** (set uji tertahan, dilacak sekali seperti `make bench`: tanpa registri, seluruh eps, satu tahap). Kedua dokumen contoh diterbitkan untuk N = 20 dengan semua varian tabel frasa tiruan dan semua titik pilihan kata disetujui. Nota dinas membawa 8 bit terlihat di halaman 1 dan 7 di halaman 2; surat telegram 9 di halaman 1 dan tidak ada di halaman 2. Setiap gambar didekode sekali, lalu pengamatan yang sama dituduh dengan dan tanpa sub-kanal OCR. Kolom terakhir adalah penerbitan bawaan tanpa kedua kanal itu, dengan id salinan, kode, dan bilangan acak cetak dan foto yang sama.

| Foto cetak (20 salinan per baris), benar / tcb / salah | Dengan OCR | Tanpa OCR | Penerbitan tanpa kedua kanal |
|---|---|---|---|
| 1600 px, nota hal. 1 | 11 / 9 / 0 | 8 / 12 / 0 | 15 / 5 / 0 |
| 1600 px, nota hal. 2 | 0 / 20 / 0 | 0 / 20 / 0 | 4 / 16 / 0 |
| 1600 px, telegram hal. 1 | 4 / 16 / 0 | 1 / 19 / 0 | 12 / 8 / 0 |
| 4000 px, nota hal. 1 | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 |
| 4000 px, nota hal. 2 | 0 / 20 / 0 | 0 / 20 / 0 | 16 / 4 / 0 |
| 4000 px, telegram hal. 1 | 12 / 8 / 0 | 5 / 15 / 0 | 20 / 0 / 0 |
| 1600 px, dua halaman (nota; telegram) | 20; 6 | 18; 3 | 20; 14 |
| 4000 px, dua halaman (nota; telegram) | 20; 18 | 20; 9 | 20; 20 |

* **Bit terbaca.** 1.765 dari 1.771 bit yang tercetak di halaman yang ditemukan, tanpa satu pun yang salah: foto, foto ISP ponsel, foto monitor, dan tangkapan layar 810 dari 811, foto cetak 1600 px 475 dari 480, foto cetak 4000 px 480 dari 480.
* **Putusan yang berubah.** OCR mengubah 27 putusan menjadi benar (13 foto satu halaman dan 14 pasangan dua halaman), tidak satu pun sebaliknya. Pada 13 foto itu skor salinan yang benar naik dari 0,94 sampai 0,99 kali ambang menjadi 1,01 sampai 1,07 kali. Foto, foto ISP ponsel, foto monitor, dan tangkapan layar sudah benar lewat pola latar (98 dari 100, dengan dan tanpa OCR).
* **Harga kanal pilihan kata di kertas.** Baris yang memuat titik pilihan kata keluar dari kanal geser ([di atas](#kanal-pilihan-kata-opsional)). Dengan skema geser v2, rencana nota dinas membawa 314 posisi geser (tanpa kanal itu 439) dan surat telegram 200 (249). Pada foto cetak, posisi geser yang terbaca turun dari median 252 menjadi 193 (nota hal. 1), 187 menjadi 121 (nota hal. 2), dan 229 menjadi 180 (telegram hal. 1), sedangkan OCR mengembalikan paling banyak 9 bit per halaman. Jadi untuk salinan yang akan dicetak, penerbitan tanpa kanal pilihan kata tetap lebih sering menyebut salinan yang benar daripada penerbitan dengan kanal itu ditambah OCR (setiap sel yang hasilnya berbeda pada tabel di atas). OCR memperkecil kerugian itu, tetapi tidak menutupnya.
* **Tuduhan salah: 0** dalam 438 pelacakan gambar dan 160 pasangan dua halaman, masing-masing dengan dan tanpa OCR; skor tak bersalah tertinggi 0,47 kali ambang. Delapan belas foto dokumen induk tanpa tanda membaca 144 bit OCR (bentuk dokumen induk) dan tidak menuduh siapa pun.
* **Batas angka ini.** Gambar dari simulator foto, ISP ponsel, monitor, dan printer, bukan perangkat sungguhan; Tesseract 5.3.4 dengan data bahasa Ubuntu 24.04; dua dokumen pendek, varian dari tabel frasa tiruan, leksikon draf tingkat A, dan satu rahasia kode per dokumen. Tesseract versi lain dapat membaca lebih buruk; bacaan yang rusak menjadi terhapus, bukan tuduhan. Angka lengkap ada di `research/ocr/hasil/`.

## Salinan yang dicetak

Pola latar bawaan (253 +/- 2) terlalu terang untuk printer. Model printer kami mengasumsikan tingkat abu-abu di atas sekitar 250 tercetak sebagai kertas polos; angka ini belum diukur pada printer sungguhan, dan kesimpulan di bagian ini paling bergantung padanya. Foto salinan yang dicetak karena itu hanya membawa kanal geser: sekitar 80 sampai 100 posisi kode terbaca per halaman dengan skema v1, dan 170 sampai 240 dengan skema v2. Dokumen yang memakai varian kalimat atau pilihan kata menambah beberapa bit lewat OCR ([di atas](#teks-terlihat-pada-bukti-gambar-ocr)). Printer sungguhan belum diuji; angka di bagian ini berasal dari simulator printer dan foto sintetis.

Angka di bagian ini diukur dengan dekoder sekarang (`research/kapasitas/`, [operasi](operasi.md#mengukur-salinan-yang-dicetak)), termasuk profil latar cetak. Hasil studi sebelumnya ada di [`results/`](results/) (`cetak_*`); kalibrasi printer dan ukuran tampilan pola di sana masih berlaku.

### Simulator printer

`print_page` di `tapak/photos.py` meniru printer laser kantor 600 dpi (preset `INKJET` untuk inkjet). Lembar hasilnya lalu difoto oleh simulator foto yang sama dengan benchmark.

1. Teks dirasterisasi di kisi printer tanpa anti-aliasing, seperti RIP printer. Glif besar ditaruh pada piksel perangkat utuh secara vertikal (seperempat piksel secara horizontal), seperti cache glif, jadi garis dasar setiap baris duduk di garis pindai utuh (42 um pada 600 dpi).
2. Tingkat abu-abu 250 ke atas menjadi kertas polos (asumsi tanpa angka pabrikan, dapat diatur lewat `white_cutoff`).
3. Warna lain diraster dengan raster AM 106 lpi pada 45 derajat.
4. Banding drum dan roda gigi menggeser garis pindai sampai 25 um.
5. Sebaran sinar laser dan toner, derau toner, dan ambang pengembangan membuat tepi huruf melebar sekitar 22 um dan bergerigi sekitar 15 um.
6. Kertas miring sampai 0,25 derajat, bergeser sampai 1 mm, dan skalanya meleset sampai 0,2 %.
7. Cahaya menyebar di dalam kertas (dot gain optis), dan kertas punya tekstur serat serta awan.

Nilainya dari literatur dan perkiraan orde besaran, bukan dari printer yang diukur. Kalibrasinya (`scripts/cetak/calibrate.py`): abu-abu 50 % tercetak 11,7 poin persentase lebih gelap, dan tingkat 245 sampai 249 tercetak sebagai titik terkecil (dL* -1,9). Yang tidak dimodelkan: koreksi nada driver, mode hemat toner, printer warna, mesin fotokopi dan pemindai, serta pemrosesan gambar di kamera ponsel (ISP ponsel simulasi, [di bawah](#foto-ponsel-dan-foto-layar-simulasi), belum dipakai untuk foto kertas cetak).

### Templat induk tepat

Dekoder geser mencocokkan setiap kelompok kata pada foto dengan templat dari dokumen induk. MuPDF menggambar glif kecil dari cache bitmap pada piksel utuh, jadi templat lama (render 4 kali lebih rapat lalu dirata-rata) menggeser kelompok kata sampai puluhan mikrometer, sama untuk setiap salinan dan foto. Templat tepat dirender pada 3.200 dpi atau lebih, saat glif digambar sebagai kurva tanpa pembulatan, per pita, lalu dirata-rata turun. Render tepat induk pada 4.800 dpi bergeser kurang dari 0,3 um terhadap templat ini untuk setiap kelompok. Hanya pita yang memuat baris teks yang dibaca dekoder geser yang dirender, dipotong ke kolom baris itu; pitanya sama dengan render seluruh halaman, jadi nilai pikselnya identik. Rendernya memerlukan sekitar 5 sampai 7 detik CPU per halaman penuh teks di mesin uji (render seluruh halaman: 7 sampai 12 detik), sekali untuk setiap halaman dan resolusi analisis per proses. `tapak web` menyimpan templat di memori (sampai 320 MB); setiap perintah `tapak trace` merendernya lagi.

Pada foto kertas cetak, templat tepat hampir tidak mengubah hasil skema v1 (studi sebelumnya, foto yang sama, 1600 px: galat bit 4,6 % dengan templat lama dan 4,8 % dengan templat tepat; dua halaman 4 dan 5 dari 20). Pada 64 pelacakan foto layar dan foto cetak benchmark README (skema v1, diukur saat templat tepat ditambahkan) putusannya identik; hanya batas peluang tuduhan salahnya yang bergeser.

### Skema geser v2

Skema v1 hanya menggeser kelompok data yang berselang-seling dengan kelompok kontrol, sekitar 80 sampai 100 posisi per halaman. Skema v2 memakai setiap kelompok kata pada baris yang memiliki paling sedikit 3 kelompok, dan kelompoknya boleh sekecil satu kata selebar 10 pt (v1: 20 pt). Halaman 1 nota dinas contoh membawa 231 posisi kata dan 21 posisi baris (v1: 82 dan 21), halaman 2 173 dan 14 (v1: 66 dan 14). Geser baris sama dengan v1.

* **Besar geser.** Dua kelompok bersebelahan kini dapat bergeser berlawanan arah, jadi celah di antaranya berubah dua kali besar geser. Supaya tidak ada celah yang berubah lebih banyak daripada di v1 (0,05 mm), setiap kelompok bergeser 0,025 mm. Diukur dari asal glif 8 salinan per dokumen (`research/kapasitas/hasil/visibilitas.jsonl`): glif bergeser paling banyak 0,025 mm (v1: 0,05), dua salinan berbeda paling banyak 0,05 mm secara horizontal (v1: 0,10), celah kata berubah paling banyak 0,05 mm, dan selisih celah kiri dan kanan sebuah kata paling banyak 0,10 mm. Dua angka terakhir sama dengan v1.
* **Tepi teks** (diukur saat tinjauan, setelah uji tertahan). v1 tidak pernah menggeser kelompok pertama dan terakhir baris, jadi tepi kiri dan kanan teks tetap rata. v2 menggesernya: dua baris berurutan yang rata di induk berbeda paling banyak 0,05 mm (sekitar 30 detik busur pada 35 cm). Ini tugas vernier dengan jarak huruf antarbaris 2,6 sampai 3,4 mm, jadi ambang 1/60-nya sekitar 26 sampai 33 detik busur: isyarat ini kira-kira di ambang, tanpa margin. Sebagai pembanding, v1 sudah menggeser kolom titik dua dan isian kepala naskah (Kepada, Dari, dan seterusnya) sampai 0,10 mm antarbaris (v2: 0,05 mm). Huruf pertama yang berbeda sering menggeser tepi tinta lebih dari 0,1 mm (lebar sisi kiri glif berbeda), yang dapat menutupinya, tetapi belum ada pengamat yang menguji. Potongan tepi kiri ada di `research/kapasitas/potongan/` (`v2_tepi_kiri_*`, `v1_tepi_kiri_*`).
* **Dekoder.** Setiap baris dibaca sebagai satu vektor: geser terukur setiap kelompok adalah gangguan baris (pergeseran dan kemiringan sepanjang baris), ditambah 0,025 mm kali tanda kelompok itu, ditambah derau. Gangguan baris diproyeksikan keluar, lalu LLR setiap tanda dihitung tepat dengan menjumlahkan semua 2^g pola tanda baris itu (paling banyak 12 kelompok per potongan baris). Pola yang hanya berbeda oleh gangguan, misalnya semua kelompok searah, tidak dapat dibedakan, dan LLR-nya nol. Sebelum itu, medan geser halaman (polinomial derajat 3 dalam koordinat halaman) dikurangkan, karena foto meninggalkan lengkungan sepanjang baris setelah rektifikasi. Medan itu dipasang tiga kali, setiap kali pada geser terukur dikurangi tanda yang diharapkan dekoder, sehingga pada salinan PDF yang persis tidak tersisa jejak tanda. Seperti dekoder lain, semuanya hanya memakai bukti, dokumen induk, dan rencana berkunci, tidak pernah kode penerima (diuji: semua kode diganti acak, pengamatan sama persis).
* **Catatan dan registri.** Catatan penerbitan dan entri dokumen registri menyimpan `shift_scheme: geser-v2`, hanya nama skema. Dokumen tanpa kolom itu, termasuk semua dokumen lama, dibaca dengan skema v1 persis seperti sebelumnya; ini diuji dengan digest pengamatan yang dihitung dengan kode sebelum perubahan ini. Halaman hasil pindai memakai skema dokumennya pada kotak kata OCR.

**Keterlihatan diputuskan lebih dulu.** Argumen lama (tidak ada glif yang bergeser lebih dari 0,10 mm antara dua salinan, 1 menit busur pada 35 cm) adalah argumen ketajaman resolusi. Kandidat pertama, yaitu menggeser kelompok data juga secara vertikal terhadap kedua tetangganya di garis dasar yang sama, adalah tugas vernier, dan ambang vernier jauh lebih halus.

* Ambang vernier untuk dua garis bersambung hanya beberapa detik busur [22]. Untuk elemen yang terpisah, ambang naik kira-kira sebanding dengan jaraknya: sekitar 1/60 jarak untuk garis [23], 2,8 sampai 3,8 % untuk dua titik di fovea [24]. Garis yang lebih panjang dari sekitar 5 menit busur tidak lagi menurunkan ambang, dan kata jauh lebih panjang.
* Celah antarkata pada nota dinas contoh 1,29 mm (persentil 10) sampai 1,85 mm (median), yaitu 13 sampai 18 menit busur pada 35 cm. Ambangnya sekitar 13 sampai 18 detik busur menurut 1/60, atau 21 sampai 41 detik busur menurut angka dua titik.
* Printer menaruh garis dasar pada garis pindai utuh [25]: 42 um pada 600 dpi dan 21 um pada 1200 dpi. Langkah vertikal yang diminta, sekecil apa pun, di kertas hilang atau menjadi paling sedikit satu garis pindai: 25 detik busur pada 600 dpi (1,4 sampai 2 kali ambang 1/60) dan 12 detik busur pada 1200 dpi (sekitar ambang). Banding drum dan roda gigi [26] menggeser seluruh garis pindai, jadi tidak menimbulkan dan tidak menutupi langkah di antara dua kata pada satu garis dasar.
* Uji coba pada benih pengembangan memastikannya: dengan geser vertikal 0,01 mm (6 detik busur), 82 % kelompok data tidak menunjukkan langkah pada foto 4000 px kertas simulasi (perkiraan dari pembulatan 600 dpi: 76 %), dan galat bitnya 38 % (1600 px: 36 %). Studi sebelumnya dengan 0,05 mm membaca hampir semua bit, tetapi langkah itu tercetak sebagai 42 atau 85 um, di atas ambang.

Karena tidak ada besar geser yang terbaca di kertas sekaligus di bawah ambang dengan margin, skema vertikal dibuang sebelum kapasitasnya diukur. Skema v2 hanya menggeser horizontal, dengan isyarat yang tidak lebih besar daripada v1 (di atas). Potongan 100 % dan 4x induk dan salinan, serta gambar selisihnya, ada di `research/kapasitas/potongan/`.

**Pemilihan dan keputusan.** Protokolnya ditetapkan di `research/kapasitas/ukur.py` sebelum pengukuran: benih pengembangan untuk setiap pilihan rancangan, benih uji tertahan dijalankan sekali di akhir, dan aturan keputusan yang ditulis lebih dulu. Pada benih pengembangan (72 foto cetak satu halaman, N = 100) satu halaman menyebut salinan yang benar: v1 0, kelompok 10 pt dengan v1 0, setiap kelompok bergeser dengan dekoder per baris saja 11, ditambah kelompok 10 pt 16, ditambah lengkung per baris 21 dan 24, ditambah medan geser halaman 27, dan semuanya bersama 29. Yang terakhir dibawa ke uji tertahan dan menjadi skema v2. Aturan keputusan: v2 menjadi bawaan penerbitan baru hanya bila lolos analisis keterlihatan, tidak mundur pada PDF, tangkapan layar, dan foto layar, tidak ada tuduhan salah di mana pun, dan foto cetak satu halaman tertahan benar paling sedikit 10 poin persentase lebih sering dengan uji tanda McNemar p < 0,01. Keempatnya lolos (tabel di bawah), jadi `tapak issue` dan halaman Terbitkan kini memakai v2; `--geser v1` dan pilihan web tetap tersedia.

### Hasil dengan profil latar bawaan

Uji tertahan: kedua dokumen contoh, N = 20 dan 100 (c = 3, eps = 10^-6, pelacakan tanpa registri seperti `make bench`, satu tahap), printer laser (salinan 1 sampai 10 untuk setiap N) dan inkjet simulasi (salinan 1 sampai 5, N = 100), foto sintetis 1600 dan 4000 px dengan sudut pandang diundi 0 sampai 30 derajat. Salinan v1 dan v2 memakai id salinan, kode, dan bilangan acak cetak dan foto yang sama, jadi setiap foto v2 berpasangan dengan foto v1. Halaman teks penuh adalah halaman 1 dan 2 nota dinas dan halaman 1 surat telegram; halaman 2 surat telegram hanya memuat 6 baris dan tidak pernah cukup sendirian. Angka v1 sekaligus pengukuran ulang [batasan 3](keamanan.md#batasan) dengan dekoder sekarang. Baris ringkas ada di `research/kapasitas/hasil/` (`uji.jsonl`, `ringkas_uji.json`).

| Halaman teks penuh | v1 | v2 |
|---|---|---|
| Posisi geser terbaca per halaman, median (nota hal. 1 / hal. 2 / telegram hal. 1) | 101 / 79 / 91 | 236 / 180 / 220 |
| Galat bit kelompok kata, laser 1600 / 4000 px | 4,9 % / 0 % | 11,8 % / 1,9 % |
| Galat bit baris, laser 1600 / 4000 px | 5,5 % / 0 % | 4,8 % / 0 % |
| Satu halaman menyebut salinan yang benar, 4000 px (laser; inkjet) | 1 dari 60; 0 dari 15 | 60 dari 60; 15 dari 15 |
| Satu halaman, 1600 px (laser; inkjet) | 1 dari 60; 0 dari 15 | 34 dari 60; 9 dari 15 |
| Skor salinan yang benar, kali ambang, median (min.), laser 4000 / 1600 px | 0,72 (0,51) / 0,66 (0,43) | 1,23 (1,00) / 1,03 (0,61) |
| Dua halaman salinan yang sama, 4000 px (laser; inkjet) | 15 dari 40; 4 dari 10 | 40 dari 40; 10 dari 10 |
| Dua halaman, 1600 px (laser; inkjet) | 7 dari 40; 2 dari 10 | 31 dari 40; 9 dari 10 |
| Tuduhan salah; skor tak bersalah tertinggi | 0; 0,42 ambang | 0; 0,56 ambang |

* **Galat bit v2 lebih tinggi.** Geser v2 setengah geser v1, dan galat bit menghitung setiap posisi yang terbaca, termasuk yang LLR-nya kecil. Pada foto laser 4000 px (N = 100), 101 dari 117 bit kata yang salah ber-LLR di bawah 0,5, sesuai bobotnya. Pada 1600 px bit yang yakin lebih sering salah daripada janji LLR-nya, pada v1 maupun v2 (v2, LLR 4 ke atas: 125 salah, sekitar 6 yang dijanjikan; `hasil/tinjauan_kalibrasi.jsonl`); itu menurunkan skor salinan yang benar, bukan menaikkan skor orang lain. Yang menentukan adalah skor salinan yang benar terhadap ambang, dan skor itu naik.
* **Atas semua 200 foto cetak satu halaman** (termasuk halaman 2 surat telegram): v1 2, v2 118. Pada 116 pasangan hanya v2 yang benar dan tidak ada pasangan sebaliknya (uji tanda McNemar satu sisi p = 1,2 x 10^-35). Semua foto ini memakai satu rahasia kode per dokumen dan 10 salinan, jadi tidak saling bebas sepenuhnya; arah yang sama terlihat pada benih pengembangan (29 dan 0 dari 72).
* **PDF, tangkapan layar, dan foto layar** (halaman 1, salinan 1 sampai 10, kedua dokumen, N = 20 dan 100): PDF 40 dan 40 dari 40, tangkapan layar 40 dan 40, foto layar 39 dan 40 (v1 dan v2). Tidak ada tuduhan salah.
* **Dokumen induk tanpa tanda** melalui setiap jenis bukti (PDF, tangkapan layar, foto layar, foto cetak laser dan inkjet 1600 dan 4000 px, kedua halaman), dilacak sebagai bukti setiap penerbitan: tidak ada yang dituduh dalam 104 pelacakan (26 gambar, masing-masing terhadap v1 dan v2 dengan N = 20 dan 100; skor tertinggi 0,66 ambang).
* **Pemeriksaan tinjauan** (`research/kapasitas/tinjauan.py`, setelah uji tertahan, 26 pelacakan): salinan v1 dilacak dengan catatan v2 dan sebaliknya, gabungan dua dan tiga salinan v2 (pita dan rata-rata piksel, dicetak dan difoto 4000 px), gabungan salinan v1 dan v2, salinan dokumen lain, induk tanpa tanda yang dicetak, dan catatan v2 yang kolom `shift_scheme`-nya dihapus. Tidak ada tuduhan salah (skor tertinggi orang lain 0,35 ambang).
* **Kolusi c = 3 di kertas** (pita atas, tengah, dan bawah dari tiga salinan di antara baris, dicetak laser dan difoto; 6 koalisi dari salinan 1 sampai 20, N = 100): tidak ada anggota yang disebut dengan v1 maupun v2, satu atau dua halaman, dan tidak ada orang tak bersalah yang disebut. Menyebut minimal satu dari tiga anggota memerlukan sekitar 1.200 posisi (`scripts/cetak/needbits.py`), jauh di atas yang dibawa satu atau dua halaman.
* **Margin di 4000 px tipis.** Skor terendah tepat di ambang (1,00). Foto ponsel sungguhan yang lebih buruk dari simulator akan menurunkan angka 60 dari 60. Angkanya juga bergantung pada rahasia kode dokumen (vektor bias dan posisi): dengan rahasia pengembangan, foto laser 4000 px halaman 2 nota dinas hanya menyebut 1 dari 8 (skor 0,90 sampai 1,02 ambang, 0 sampai 4 bit kata salah), dan halaman teks penuh 17 dari 24.

### Profil latar cetak (opsional)

`tapak issue ... --latar cetak` menggambar pola latar 242 +/- 5 (tingkat 237 sampai 247), di bawah ambang yang diasumsikan model printer. Dekodernya sama, dan catatan penerbitan menyimpan pengaturan pola. Profil ini dipilih dari tiga kandidat (245 +/- 4, 242 +/- 5, 238 +/- 8) setelah melihat hasilnya pada cetakan dan foto simulasi tertentu, lalu diukur ulang pada cetakan baru (`results/cetak_summary_r1.json`). Angka sekarang dari uji tertahan `research/kapasitas` dengan dekoder sekarang (strata kejenuhan dan uji pilot, [batasan 4](keamanan.md#batasan)), nota dinas, N = 100, salinan 1 sampai 6:

| | Laser 1600 px | Laser 4000 px | Inkjet 1600 px |
|---|---|---|---|
| Galat bit kanal latar, hal. 1 / hal. 2 | 0,5 % / 0,3 % | 2,3 % / 0,1 % | 0,3 % (hal. 1) |
| Satu halaman menyebut salinan yang benar (v1; v2) | 12 dan 12 dari 12 | 12 dan 12 dari 12 | 6 dan 6 dari 6 |
| Skor salinan yang benar, median, kali ambang | 4,4 | 4,4 | 4,4 |
| Dua halaman (v1; v2) | 6 dan 6 dari 6 | 6 dan 6 dari 6 | |
| Tuduhan salah; skor tak bersalah tertinggi | 0; 0,46 ambang | 0; 0,47 ambang | 0; 0,47 ambang |

* **Kolusi c = 3 di kertas, profil cetak** (uji tertahan, 6 koalisi dari salinan 1 sampai 20, laser 1600 px): satu halaman menyebut minimal satu anggota pada 6 dari 6 halaman dengan v1 maupun v2, ketiganya pada 5 dan 6 dari 6, tanpa orang tak bersalah (skor tertinggi 0,42 ambang).

Studi sebelumnya, dengan dekoder latar sebelum strata kejenuhan dan skema v1 (`results/cetak_summary_r1.json`, 20 salinan, 1600 dan 4000 px), memberi hasil serupa: satu halaman 40 dari 40 foto per resolusi dan dua halaman 20 dari 20. Rinciannya:

* **Kolusi c = 3 di kertas.** Tiga salinan dipotong menjadi pita atas, tengah, dan bawah di ruang kosong antarbaris, disatukan dalam satu lembar, dicetak, lalu difoto (16 koalisi baru dari salinan 1 sampai 20, 1600 px). Satu halaman menyebut minimal satu anggota pada 31 dari 32 halaman dan ketiganya pada 23 dari 32. Halaman yang gagal difoto miring 29 derajat dengan resolusi efektif 97 dpi; polanya tidak terdeteksi (z = 0,56), jadi jawabannya "tidak cukup bukti". Dua halaman: 16 dari 16 dan 15 dari 16. Tidak ada orang tak bersalah yang disebut (skor tertinggi 58 % ambang).
* **Printer inkjet simulasi** (halaman 1 salinan 1 sampai 10, 1600 px): 10 dari 10, galat bit 3,6 % (median 0 %).
* **Foto yang buruk** tetap melemahkan pola: tiga foto terburuk bergalat bit 25 sampai 32 % (hanya satu di antaranya terlalu terang, 43 % piksel jenuh), tetapi ketiganya masih menyebut salinan yang benar.
* **Pada cetakan dan foto yang ikut memilih profil** (`results/cetak_summary.json`) hasilnya serupa: satu halaman 40 dari 40 per resolusi, dua halaman 20 dari 20, koalisi 32 dari 32 (ketiganya 27), inkjet 10 dari 10, tanpa tuduhan salah.

Harganya tampilan. Seluruh halaman tampak abu-abu muda: dL* -3,4 terhadap kertas pada laser simulasi dan -4,5 di layar. Teksturnya di ambang terlihat: S-CIELAB pada 35 cm rata-rata 1,1 dan persentil 95 sebesar 3,5 (pola layar bawaan: 0,4 dan 0,8; raster abu-abu polos setingkat: 0,75 dan 2,0), dengan 1 sebagai beda yang nyaris terlihat (`scripts/cetak/visibility.py`). Karena itu profil ini tidak menjadi bawaan dan TAPAK menampilkan peringatan saat dipakai. Printer biasanya menyisakan tepi putih beberapa milimeter, sehingga halaman abu-abu tampak berbingkai putih. Belum diuji dengan printer, ponsel, maupun pengamat sungguhan.

## Foto ponsel dan foto layar (simulasi)

Semua angka di bagian ini berasal dari simulasi. Ponsel, monitor, dan ISP sungguhan belum diuji, jadi angkanya menunjukkan kepekaan dekoder terhadap model kami, bukan hasil di perangkat nyata.

### Simulator

`tapak/ponsel.py` menambah dua bagian opsional ke `tapak/photos.py`. Tanpa keduanya keluaran simulator sama persis dengan sebelumnya: `make photos` dan `make photos-cetak` dengan benih 2026 dibuat ulang dan hash ke-58 berkasnya sama, dan `tests/test_ponsel.py` menyimpan hash emasnya.

**ISP ponsel** (profil `ponsel`; profil `netral` adalah simulator lama). Urutannya mengikuti pipa kamera ponsel [7, 8]:

1. *HDR beruntun*: 2 sampai 8 bingkai yang sengaja kurang terang (0 sampai 2 stop) digabung, sehingga varians derau dibagi jumlah bingkai [7, 8]. Banyaknya kurang terang tidak disebut sumbernya, jadi rentangnya asumsi.
2. *Pengurangan derau*: filter terpandu [11] pada skala halus dan kasar (radius 1 sampai 2 dan 4 sampai 10 piksel bingkai 12 MP), dengan ambang 1 sampai 2,5 kali derau setempat dari model derau dua parameter yang dilaporkan ponsel [9, 10]. Penyaring bilateral bekerja paling baik di sekitar 2 kali derau [12]. Cara ini menghapus tekstur berkontras rendah, yang dikenal sebagai kehilangan tekstur pada ponsel [13, 14].
3. *Pemetaan nada lokal*: lapisan dasar dan detail di ranah log [15]; kontras dasar dikali 0,5 sampai 0,85, detail 1,0 sampai 1,3, bagian terang terbesar diletakkan di 85 sampai 97 % putih, lalu bahu sorotan lembut. Nilainya asumsi di dalam metode itu.
4. *Penajaman*: unsharp mask dengan coring, radius 1 sampai 2 kali blur lensa, kekuatannya diatur agar tepi tajam melampaui 10 sampai 40 %. Imatest mencatat 7 % untuk penajaman sedang di DSLR, menyebut 35 % kemungkinan mengganggu, dan menyebut lingkaran cahaya besar pada ponsel [16].
5. *JPEG kamera*: kualitas 85 sampai 95, "rentang pemakaian umum" `android.jpeg.quality` yang juga mengatur kualitas HEIC [9]. HEIC sendiri tidak disimulasikan. Setelah itu pengguna memotong dan WhatsApp mengecilkan serta mengompresi dua kali seperti sebelumnya.

**Monitor** (jenis `fotolayar`). Penampil PDF menampilkan halaman pas setinggi 80 sampai 92 % layar, dengan latar penampil terang atau gelap.

* Monitor: 23,8 inci 1920 x 1080 (92,6 ppi), 27 inci 2560 x 1440 (108,8 ppi), 27 inci 3840 x 2160 (163,2 ppi), dan laptop 13,3 inci 2560 x 1600 (227 ppi). Kepadatan piksel dihitung dari geometri. Di survei Steam September 2026, 1920 x 1080 adalah layar utama 47,9 % pengguna dan 2560 x 1440 27,0 % [17] (pengguna gim, bukan kantor).
* Subpiksel RGB tegak, masing-masing sepertiga jarak piksel, dengan matriks hitam; bagian menyala 70 sampai 90 % lebarnya dan 75 sampai 92 % tingginya (asumsi).
* Gamma 2,0 sampai 2,4 (sRGB sekitar 2,2 [18], BT.1886 2,4 [19]); putih 100 sampai 300 cd/m2 (layar kantor umumnya berlatar terang 140 sampai 180 cd/m2 [20]); kontras 800 sampai 3000 (asumsi); lampu latar 0 sampai 20 % lebih gelap di sudut (asumsi).
* Penurunan terang menurut sudut pandang: 75 % pada 35 sampai 50 derajat mendatar dan 22 sampai 45 derajat tegak. RTINGS mengukur sudut 75 % itu 39 sampai 42 derajat pada monitor IPS dan 22 derajat dari bawah pada panel lemah [21].
* Pantulan cahaya ruangan 0,5 sampai 4 % putih, dan pantulan lampu (opsional) 5 sampai 50 % putih: lampu kantor paling terang sekitar 3000 cd/m2 pada sudut yang diizinkan [20], dikali pantulan permukaan depan sekitar 1 sampai 4 %.
* Kamera: bingkai 12 MP, setara 26 mm, jarak 25 sampai 60 cm (asumsi), blur lensa sigma 0,45 sampai 0,9 piksel (MTF50 sekitar 0,21 sampai 0,42 siklus per piksel; acuan Imatest tanpa penajaman 0,31 [16]), filter Bayer RGGB dan demosaik peka tepi (OpenCV). Setiap piksel kamera mengintegrasikan 3 x 3 sampel setelah blur lensa, jadi kisi subpiksel tercuplik seperti oleh sensor dan menjadi moire. `tests/test_ponsel.py` memeriksa bahwa puncak spektrumnya berada di frekuensi alias yang diramalkan. Kontras moire di model ini (rms terhadap kertas, selisih `layar_netral` dan `layar_ideal`; pola latar sekitar 0,8 %) bermedian sekitar 2,5 % pada monitor 93 dan 109 ppi dari 30 cm, paling besar 1,6 % dari 45 dan 60 cm, dan paling besar 1,1 % pada 163 dan 227 ppi, yang kisinya sering terhapus blur lensa Gaussian. Lensa sungguhan meredam frekuensi tinggi lebih lambat, jadi moire layar berkepadatan tinggi mungkin terlalu lemah di sini.

Yang tidak disimulasikan: ponsel dan monitor sungguhan, HEIC, panel 6 bit dengan FRC, kedipan PWM lampu latar, ClearType, OLED dan PenTile, silang warna antara filter kamera dan warna monitor, super-resolusi beruntun pengganti demosaik, dan ISP berbasis model.

### Protokol

Protokol dan semua benih ditetapkan di `research/ponsel/ukur.py` sebelum pengukuran pertama dan masuk riwayat repositori lebih dulu.

* Dua dokumen induk fiktif, nota dinas dan surat telegram contoh, masing-masing diterbitkan untuk N = 20 penerima (c = 3, eps = 10^-6) dengan id salinan berbenih dan skema geser v1 (sebelum v2 menjadi bawaan). Bukti adalah halaman 1.
* Dua set benih yang terpisah: set **pengembangan** dipakai untuk memilih perubahan dekoder, set **uji** dibuat dan dilacak sekali di akhir dengan kedua dekoder.
* Setiap salinan menghasilkan satu gambar per kondisi. Kondisi foto berbagi adegan, pose, dan derau sensor, begitu pula kondisi layar, jadi selisihnya hanya ISP atau layar:
  * `foto_netral` (foto `make photos`), `foto_ponsel` (ISP penuh), dan `foto_nr`, `foto_hdr`, `foto_nada`, `foto_tajam`, `foto_jpeg` (satu langkah ISP saja, untuk ablasi);
  * `layar_ideal` (monitor tanpa struktur subpiksel), `layar_netral` (dengan subpiksel, jadi moire), `layar_ponsel` (ditambah ISP), `layar_silau` (ditambah pantulan lampu).
* Sudut pandang 0, 10, 20, dan 30 derajat, keempat monitor, dan jarak 30, 45, dan 60 cm mengikuti rancangan tetap per salinan.
* Halaman 1 dokumen induk tanpa tanda difoto lewat `foto_ponsel`, `layar_netral`, dan `layar_ponsel`, 10 gambar per dokumen, kondisi, dan set. Tidak boleh ada yang dituduh.
* Pelacakan seperti `make bench`: tanpa registri, seluruh eps. Galat bit dihitung terhadap kode salinan yang bocor.

### Perubahan dekoder

Hanya kanal latar pada bukti gambar yang berubah. Halaman PDF yang diteruskan dan pas di bingkai induk didekode persis seperti sebelumnya; halaman PDF yang diskalakan, digeser, atau tanpa lapisan teks yang cocok dibaca sebagai gambar, jadi ikut disaring.

1. **Penyaring komponen berkala.** Moire adalah beberapa sinusoid kuat di kertas, sedangkan pola latar berpita lebar (sel berkunci yang saling bebas). Dalam petak 128 piksel yang bertumpuk setengah, setiap puncak spektrum yang lebih dari 6 kali rata-rata tetangganya, dan tidak dekat frekuensi nol, dibuang bersama tetangga terdekatnya (`suppress_periodic`). Frekuensi moire bergeser di sepanjang halaman karena perspektif, jadi penyaringan dilakukan per petak.
2. **Penyisihan pencilan dua arah.** Piksel yang menyimpang lebih dari 8 % dari tingkat kertas sudah disisihkan bila lebih gelap (tinta tambahan). Kini piksel yang lebih terang juga disisihkan: lingkaran cahaya penajaman di sisi teks. Penyisihan dilakukan setelah penyaringan, supaya puncak moire tidak ikut terbuang, lalu modulasi dihitung ulang dan disaring sekali lagi.

Keduanya hanya melihat bukti, sebelum tanda sel berkunci diterapkan, jadi uji umpan, uji pilot, dan batas tuduhan salah tidak berubah. Tidak ada ambang atau aturan putusan yang diubah. `tests/test_background_moire.py` memeriksa bahwa mengganti semua kode penerima tidak mengubah satu pengamatan pun.

Metode dipilih pada set pengembangan saja (`research/ponsel/kandidat.py`, ringkasan di `research/ponsel/hasil/pengembangan_kandidat.jsonl`). Aturan pemilihan, dinyatakan setelah kandidat pertama dan grid kecil dinilai tetapi sebelum kandidat terakhir: tidak boleh ada putusan yang hilang di kondisi mana pun, tidak boleh ada tuduhan pada induk tanpa tanda, dan margin harus membaik pada foto yang terpengaruh. Kandidat lain ditolak: strata "tanpa tekstur" (kertas rata, perluasan bobot kliping) kehilangan putusan pada empat kondisi, dan penyisihan pencilan terang pada 5 % tidak stabil (foto ponsel jauh lebih baik, tetapi foto dengan penajaman saja turun dari 37 menjadi 34 benar).

### Hasil

Set uji yang ditahan, dilacak sekali dengan dekoder lama (sebelum studi ini) dan sekali dengan dekoder baru. Setiap baris berisi 40 foto (2 dokumen x 20 salinan); baris induk tanpa tanda berisi 20. "tcb" berarti "tidak cukup bukti". Galat bit dan z pola dihitung per foto, lalu diambil mediannya. Kolom geser memakai dekoder baru; kanal geser tidak berubah.

| Kondisi | Benar / tcb / salah, lama | Benar / tcb / salah, baru | Galat bit latar, median per foto (lama; baru) | z pola median (lama; baru) | Geser: posisi; galat median |
|---|---|---|---|---|---|
| foto tanpa ISP | 38 / 2 / 0 | 38 / 2 / 0 | 1,5 %; 1,5 % | 49,4; 49,4 | 97; 4,6 % |
| foto, ISP ponsel | 40 / 0 / 0 | 40 / 0 / 0 | 9,1 %; 5,0 % | 30,0; 36,0 | 97; 3,3 % |
| hanya pengurangan derau | 38 / 2 / 0 | 38 / 2 / 0 | 2,1 %; 2,0 % | 46,5; 46,5 | 97; 4,6 % |
| hanya HDR beruntun | 40 / 0 / 0 | 40 / 0 / 0 | 1,8 %; 1,7 % | 50,4; 50,6 | 97; 4,6 % |
| hanya pemetaan nada lokal | 37 / 3 / 0 | 37 / 3 / 0 | 2,4 %; 2,3 % | 46,2; 46,3 | 97; 4,4 % |
| hanya penajaman | 38 / 2 / 0 | 38 / 2 / 0 | 8,8 %; 7,4 % | 30,4; 33,9 | 97; 3,3 % |
| hanya JPEG kamera | 38 / 2 / 0 | 38 / 2 / 0 | 1,6 %; 1,6 % | 49,0; 49,1 | 97; 5,2 % |
| monitor tanpa subpiksel, tanpa ISP | 31 / 9 / 0 | 31 / 9 / 0 | 2,7 %; 2,5 % | 31,8; 32,1 | 94; 3,9 % |
| monitor (moire), tanpa ISP | 32 / 8 / 0 | 32 / 8 / 0 | 5,8 %; 4,1 % | 27,5; 30,2 | 94; 3,9 % |
| monitor (moire), ISP ponsel | 39 / 1 / 0 | 39 / 1 / 0 | 4,5 %; 3,1 % | 38,5; 41,2 | 94; 3,9 % |
| monitor, ISP ponsel, silau | 39 / 1 / 0 | 39 / 1 / 0 | 3,5 %; 3,3 % | 40,0; 41,0 | 94; 3,3 % |
| induk tanpa tanda, foto, ISP ponsel | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,2; 0,5 | - |
| induk tanpa tanda, monitor (moire), tanpa ISP | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,6; 0,6 | - |
| induk tanpa tanda, monitor (moire), ISP ponsel | 0 / 20 / 0 | 0 / 20 / 0 | - | 0,4; 0,3 | - |

* **Tidak ada tuduhan salah** pada 1.000 pelacakan per dekoder (set pengembangan dan uji), termasuk 120 foto induk tanpa tanda. Gerbang pola latar lolos sekali pada induk tanpa tanda (dekoder lama, set pengembangan, z = 3,00 tepat di ambang); tidak ada yang dituduh, sesuai laju lolos gerbang yang terukur di [batasan 4](keamanan.md#batasan).
* **Tahap yang paling merugikan pola latar adalah penajaman.** Dengan dekoder lama, penajaman saja menaikkan galat bit latar dari 1,5 % menjadi 8,8 % dan menurunkan z dari 49 menjadi 30. Penajaman yang sama justru memperbaiki kanal geser (galat 4,6 % menjadi 3,3 %). Moire menaikkan galat latar dari 2,7 % menjadi 5,8 % (monitor yang sama dengan dan tanpa subpiksel). Pengurangan derau hampir tidak merugikan (2,1 %), JPEG kamera tidak berpengaruh, dan HDR beruntun mencegah kertas jenuh (40 dari 40).
* **Kegagalan yang tersisa tidak disebabkan ISP atau moire.** Tanpa HDR, setiap "tidak cukup bukti" terjadi pada foto yang 87 sampai 99,5 % kertasnya jenuh di sensor ([batasan 4](keamanan.md#batasan)), sebagian juga beresolusi rendah (laptop 13 inci dari 45 cm, 43 sampai 46 dpi efektif). Pemetaan nada lokal tanpa HDR menggeser kertas jenuh itu ke bawah putih menjadi bidang rata, sehingga strata kejenuhan tidak mengenalinya: 3 gagal, sedangkan tanpa ISP 2. Dengan ISP ponsel penuh, HDR dan pemetaan nada lokal dalam model kami menjaga kertas di bawah putih; satu-satunya kegagalan adalah laptop dari 60 cm, ketika halaman hanya mengisi 20 % bingkai dan tidak ditemukan.
* **Per monitor dan jarak** (ISP ponsel, kedua dekoder): 23,8 inci, 27 inci QHD, dan 27 inci 4K masing-masing 10 dari 10, laptop 9 dari 10; 30 cm 16 dari 16, 45 cm 16 dari 16, 60 cm 7 dari 8. Tanpa ISP: 23,8 inci 7 dari 10, QHD 10 dari 10, 4K 8 dari 10, laptop 7 dari 10.
* **Dekoder baru** tidak mengubah putusan di set uji, tetapi memperlebar margin: pada foto dengan ISP ponsel galat bit latar turun dari 9,1 % menjadi 5,0 % (z 30 menjadi 36), pada monitor tanpa ISP dari 5,8 % menjadi 4,1 %, dan batas peluang tuduhan salah terlemah di antara jawaban benar di baris itu membaik dari 10^-6,0 menjadi 10^-13,6. Di set pengembangan dekoder baru menambah satu jawaban benar pada monitor tanpa ISP dan satu pada pemetaan nada lokal saja.
* **Benchmark README** (`make bench`, penerbitan 20 salinan dari benih riset 2026, benih foto 2026, `docs/results/bench_photos.json`): dengan penerbitan skema v1 saat studi ini, `make photos-ponsel` 32 dari 32 benar, `make photos-layar` 31 dari 32 (gagal: laptop 13 inci dari 45 cm, halaman mengisi 26 % bingkai), tanpa tuduhan salah. Sejak penerbitan benchmark memakai skema v2, keduanya 32 dari 32: adegan laptop itu disebut lewat kanal geser saja (batas 7,3 x 10^-8). Pada `make photos` dan `make photos-cetak` putusan ke-64 pelacakan sama dengan hasil dekoder lama dari penerbitan yang sama; batas peluang tuduhan salah ke-24 pelacakan cetak tidak berubah, dan pada foto layar hanya bergeser sedikit (median perubahan log10 -0,0004, paling besar 0,6). Pengukuran pertama, dengan penerbitan id acak di mesin uji, memberi putusan yang sama (32 dari 32 dan 31 dari 32, gagal pada adegan laptop yang sama); hasilnya ada di `research/ponsel/hasil/bench_lama.json` dan `bench_baru.json`.

Yang belum diuji: ponsel, monitor, dan ISP sungguhan. Semua angka di atas bergantung pada model dan rentang parameter yang kami pilih; ISP ponsel yang menajamkan lebih keras, mengurangi derau lebih agresif pada skala sel pola (2 mm), atau mengompresi sorotan lebih rata dapat memberi hasil yang lebih buruk. Dengan skema v1 kanal geser pada foto layar (sekitar 94 posisi per halaman) tidak cukup sendirian untuk menyebut nama, jadi foto layar bergantung pada pola latar seperti foto biasa. Skema v2 membaca sekitar 250 posisi per halaman pada foto benchmark dan kadang cukup sendirian (dua foto benchmark tanpa pola latar yang terbaca), tetapi foto layar tetap terutama bergantung pada pola latar.

## Tangkapan layar dari penampil PDF

Simulator tangkapan layar `tapak/photos.py` mengecilkan render 200 dpi dengan rata-rata luas, jadi tidak meniru cara penampil menggambar halaman pada resolusi layar. `research/layar/` menggambar halaman dengan pustaka penampil sungguhan: MuPDF lewat pymupdf (SumatraPDF, mupdf, zathura), Poppler Splash lewat `pdftoppm` dengan dan tanpa anti-aliasing (Okular, qpdfview), dan Poppler Cairo lewat `pdftocairo` (Evince, GNOME Papers, Atril). Bingkai penampil, jendela yang hanya memperlihatkan sebagian halaman, dan kompresi aplikasi pesan disimulasikan. Protokol, benih, dan aturan batas bawah ditetapkan di `research/layar/ukur.py` sebelum pengukuran ([operasi](operasi.md#mengukur-tangkapan-layar), [README studi](../research/layar/README.md)).

### Letak glif

`research/layar/kuantisasi.py` menggambar glif yang digeser sepersekian piksel dan mengikuti titik berat tintanya. MuPDF dan Splash meletakkan garis dasar setiap baris pada piksel utuh, Cairo pada seperempat piksel. Secara horizontal glif diletakkan pada seperempat piksel, kecuali Splash tanpa anti-aliasing (piksel utuh). Pada kerapatan tinggi subpiksel ditinggalkan: Splash meletakkan glif 11 pt pada piksel utuh pada 225 dpi, MuPDF pada setengah piksel mulai 180 dpi (dan setengah piksel vertikal di bawah 56 dpi, dengan langkah 0,47 sampai 0,55 piksel). Geser baris 0,05 mm adalah 0,08 sampai 0,3 piksel pada 40 sampai 150 dpi, dan geser kelompok kata v2 (0,025 mm) 0,04 sampai 0,15 piksel. Geser baris karena itu hilang dibulatkan atau memindahkan baris satu langkah kisi (satu piksel, pada Cairo seperempat piksel); geser kata tersisa sebagai rata-rata pembulatan glif satu kelompok.

### Protokol

* Nota dinas dan surat telegram contoh, `tapak issue --benih-riset` untuk N = 20 penerima, sekali dengan skema geser v2 dan sekali dengan v1 dari benih yang sama. Bukti adalah halaman 1. Set pengembangan (benih 7501, 7502) untuk setiap pilihan dekoder, set uji (7601, 7602) dibuat dan dilacak sekali di akhir.
* Resolusi efektif 28, 32, 40, 48, 56, 64, 72, 84, 96, 120, dan 150 dpi. Format: PNG; aplikasi pesan (sisi panjang paling besar 1600 px, JPEG mutu 68 sampai 72 lalu 58 sampai 62); dan diperkecil (digambar pada 1,5 kali resolusi oleh layar berkerapatan tinggi, lalu diperkecil aplikasi pesan ke resolusi efektif dan dikompresi seperti tadi). Halaman saja dan halaman di jendela penampil bergantian per salinan. Jendela sebagian memperlihatkan 55 % tinggi halaman, dari atas atau mulai 25 %, pada 64 sampai 150 dpi.
* Set uji: 1.188 tangkapan halaman utuh v2 (12 per penggambar, resolusi, dan format), 594 tangkapan v1, 132 Splash tanpa anti-aliasing, 240 jendela sebagian, dan 96 tangkapan induk tanpa tanda yang dilacak terhadap kedua penerbitan. Pelacakan seperti `make bench` (tanpa registri, seluruh eps, satu tahap), lewat jalur produksi; pengamatan yang sama dituduh dengan semua kanal, kanal geser saja, dan kanal latar saja.

### Perubahan dekoder

Hanya baris kanal geser pada bukti gambar yang berubah, dan hanya bila garis dasarnya jatuh pada kisi piksel gambar (`ch_shift.rounded_rows`).

* **Gerbang.** Posisi baris kontrol (baris tanpa tanda) dipetakan ke gambar lewat homografi registrasi. Bila paling sedikit 8 baris kontrol terukur dan posisinya modulo satu piksel, atau modulo seperempat piksel, berkumpul dengan panjang resultan rata-rata paling sedikit 0,7, garis dasar halaman itu dibulatkan ke kisi gambar: tangkapan yang tidak diskalakan ulang. Tangkapan MuPDF dan Splash yang tidak diskalakan umumnya memberi 0,9 sampai 0,98 dari 56 dpi; foto, foto monitor, dan tangkapan dari simulator `tapak/photos.py` paling besar 0,43. Benchmark README tidak berubah byte demi byte, karena gerbangnya tidak pernah terbuka di sana.
* **Model.** Penggambar menaruh baris j pada piksel round(k y_j + phi), dengan k dan phi tidak diketahui. Setiap baris kontrol membatasi (k, phi) pada satu pita. Dengan prior rata pada irisan pita, LLR tanda baris data adalah log perbandingan luas bagian irisan tempat garis dasarnya plus atau minus geser jatuh pada piksel yang terukur. Geser yang hilang dibulatkan memberi LLR 0, geser yang memindahkan baris satu piksel terbaca, dan peluang 1 % untuk piksel yang tidak diramalkan membatasi abs LLR pada 4,6. Model hanya memakai bukti, garis dasar induk, dan baris mana yang tanpa tanda, tidak pernah kode penerima.
* **Pemilihan.** Pada set pengembangan dekoder lama memberi 204 bit baris yang salah dengan yakin (abs LLR paling sedikit 4) dan bit baris berbobot di atas 0,95 salah 4,5 % (terkalibrasi 0,5 %). Penyebabnya: dengan jarak baris yang bukan kelipatan piksel, pembulatan baris tetangga bergeser pelan lalu melompat, sehingga baris data di antara tetangga yang melompat dan yang tidak berada setengah piksel dari tempatnya, apa pun tandanya. Aturan pemilihan ditetapkan sebelum kandidat dinilai: tanpa tuduhan salah, tanpa putusan benar yang hilang per penggambar dan format, bit baris salah yakin turun paling sedikit separuh, dan baris model kandidat terkalibrasi. Empat kandidat dinilai dalam tiga putaran tanpa mengubah aturan; galat seragam yang saling bebas dan kisi piksel utuh saja gagal pada syarat ketiga (204 menjadi 112), kisi setengah piksel gagal pada syarat keempat, dan kisi 1 dan 1/4 piksel lolos (204 menjadi 101, tepat di batas separuh).

### Hasil (set uji)

| Penggambar | Batas bawah semua kanal: PNG / pesan / diperkecil | Batas bawah geser saja | Bit kata salah: 28 sampai 48 / 56 sampai 84 / 96 sampai 150 dpi (PNG) | Galat bit latar pesan: 28 sampai 48 / 56 sampai 84 / 96 sampai 150 dpi |
|---|---|---|---|---|
| MuPDF | 28 / 32 / 32 dpi | 120 / 120 / 84 dpi | 35 / 14 / 3 % | 15 / 3,9 / 0,8 % |
| Poppler Splash | 32 / 32 / 40 dpi | 96 / 96 / tidak pernah | 35 / 14 / 2 % | 16 / 4,0 / 1,1 % |
| Poppler Cairo | 28 / 32 / 40 dpi | 96 / 96 / 72 dpi | 35 / 14 / 3 % | 15 / 3,8 / 0,8 % |
| Splash tanpa anti-aliasing | 48 / 56 dpi (PNG / pesan) | tidak pernah | 44 / 37 / 25 % | 17 / 4,2 / 1,3 % |

Batas bawah adalah resolusi terendah yang mulai dari sana setiap tangkapan halaman utuh pada resolusi itu dan semua resolusi di atasnya menyebut salinan yang benar; 28 berarti sampai resolusi terendah yang diuji. Batas geser saja dekat ambang dan bergeser antarbenih: pengulangan saat peninjauan dengan benih baru (4 tangkapan per sel) memberi MuPDF 96 / 96 / tidak pernah, Splash 120 / 120 / tidak pernah, dan Cairo 96 / 96 / 84 dpi; batas semua kanal sama atau lebih rendah ([README studi](../research/layar/README.md#pengulangan-dengan-benih-baru-peninjauan)).

* **Pola latar menentukan putusan.** Dengan kanal latar saja putusannya sama di setiap sel. Setiap kegagalan halaman utuh adalah halaman yang tidak ditemukan pada 28 sampai 32 dpi (Splash tanpa anti-aliasing sampai 48 dpi); setiap halaman yang ditemukan disebut, skor salinan yang benar paling kecil 1,9 kali ambang (median 4,6 sampai 4,7 kali pada PNG, 2,8 kali pada pesan 28 sampai 32 dpi). Kanal geser menaikkan skor itu, tetapi sendirian baru cukup dari sekitar 96 dpi (median skor geser saja 0,3 kali ambang pada 28 sampai 32 dpi, 1,0 pada 56 sampai 84 dpi, dan 1,2 dari 96 dpi). Skema v1 memberi batas semua kanal yang sama, tetapi kanal gesernya tidak pernah cukup sendirian (skor paling besar 0,76 ambang).
* **Baris, sebelum dan sesudah** (pengukuran yang sama, didekode dua kali): bit baris salah yakin 470 menjadi 243; MuPDF PNG 50 menjadi 25 dan pesan 53 menjadi 31, Splash 116 menjadi 0, Splash tanpa anti-aliasing 33 menjadi 0, Cairo PNG 52 menjadi 31 dan pesan 57 menjadi 47, tangkapan yang diperkecil tetap 109. Baris yang dibaca model kisi: 8.458 berbobot di atas 0,95 dengan 2 salah, 209 berbobot 0,8 sampai 0,9 dengan 8,6 % salah (terkalibrasi 7,6 %). Putusan kanal geser saja benar 542 kali (lama 516; 27 bertambah, 1 hilang), putusan semua kanal sama (2.041), dan tidak ada tuduhan salah pada keduanya. Pada salinan skema v1 (dokumen lama) putusannya sama dan bit baris salah yakin turun dari 135 menjadi 79.
* **Kelompok kata** dari 56 dpi ke atas mendekati terkalibrasi (bobot di atas 0,95 salah 0,4 %, terkalibrasi 0,2 %), di bawah 56 dpi terlalu yakin (4,4 % dan 0,9 %). Tangkapan Poppler yang digambar pada 180 dan 225 dpi lalu diperkecil ke 120 dan 150 dpi kehilangan geser kata (bit salah 16 sampai 17 %, geser saja menyebut 4 dari 24) karena Splash meninggalkan subpiksel pada kerapatan itu.
* **Bobot yang terlalu yakin.** Baris yang tidak lolos gerbang tetap memakai model Gaussian: tangkapan yang diskalakan ulang (diperkecil, juga pesan 150 dpi yang dibatasi 1600 px), MuPDF di bawah 56 dpi, dan Cairo di bawah 64 dpi (gerbang tidak pernah terbuka pada 28 sampai 40 dpi dan jarang pada 56 dpi). Pada 28 sampai 48 dpi bit baris v2 dengan abs LLR paling sedikit 2 salah 24 sampai 27 % (MuPDF) dan 14 sampai 18 % (Cairo); Splash 0 %. Bobot pola latar setelah JPEG juga terlalu yakin di kelompok tertinggi: bobot di atas 0,95 salah 1,8 % pada 28 sampai 48 dpi (terkalibrasi 0,7 %), 0,9 % pada 56 sampai 84 dpi (0,2 %), dan 0,5 % dari 96 dpi (0,1 %). Batas deteksi dengan laju (1 - w)/2 tidak berlaku untuk tangkapan layar ([batasan 12](keamanan.md#batasan)); batas tuduhan salah tidak bergantung padanya.
* **Jendela sebagian.** Jendela dari atas halaman ditemukan dan disebut pada 120 dari 120 tangkapan; jendela dari tengah halaman hanya ditemukan pada 60 dari 120 (registrasi gagal), dan setiap yang ditemukan disebut.
* **Tidak ada tuduhan salah** dalam 2.346 pelacakan set uji dan 1.294 pelacakan set pengembangan, termasuk 192 dan 96 pelacakan induk tanpa tanda (skor tertinggi 0,35 dan 0,39 ambang). Skor tak bersalah tertinggi 0,64 ambang. Peringatan pola penghapusan muncul pada 3 dari 2.154 pelacakan salinan jujur.

Yang belum diuji: PDF.js, PDFium, Adobe Reader, pengaturan hinting Okular (`pdftoppm` 24.02 tidak menyediakannya), layar dan aplikasi pesan sungguhan, dan halaman selain halaman 1 dua dokumen contoh. Satu rahasia kode per dokumen dan set, jadi tangkapan dalam satu sel tidak saling bebas sepenuhnya.

## Keputusan desain yang menyimpang dari spesifikasi awal

| Spesifikasi | Yang dibangun | Alasan |
|---|---|---|
| Kode penuh ditanam di setiap kanal | kanal teks membawa seluruh m bit; setiap halaman membawa irisannya sendiri di kanal fisik; tuduhan hanya dihitung atas posisi yang terbaca dengan ambang ketat untuk himpunan itu | c=3, eps=10^-6 memerlukan sekitar 3000 bit, sedangkan geser kata dan baris hanya memuat sekitar 90 (skema v1) sampai 250 (skema v2) bit per halaman. Skala c^2 ln(1/eps) adalah batas bawah untuk kode tahan kolusi apa pun |
| Geser 0,01 sampai 0,03 mm | skema v1: 0,05 mm (dapat diatur, maksimum 0,05 mm); skema v2: 0,025 mm per kelompok, setiap kelompok membawa bit | satu geser 0,01 sampai 0,03 mm hanya 0,1 sampai 0,3 piksel pada foto ponsel satu halaman A4. Skema v2 baru terbaca dengan membaca semua kelompok satu baris bersama dan mengurangkan medan geser halaman, dan terutama pada foto 4000 px ([skema geser v2](#skema-geser-v2)) |
| "Selisih piksel tak terlihat" | didefinisikan secara geometris: di antara dua salinan mana pun, tidak ada glif yang bergeser lebih dari 0,1 mm per sumbu (1 menit busur pada jarak baca 35 cm). Diuji pada 600 dpi: perbedaan piksel hanya ada di kotak kata yang digeser (di luar itu hanya pola latar, maksimum 4 tingkat abu-abu) dan pusat tinta bergeser sesuai rencana | tanda geometris mengubah posisi tepi, bukan kontras; ambang tingkat abu-abu tidak bermakna untuk itu |
| Pola latar didekode dengan korelasi terhadap kandidat | korelasi buta per bit (spread spectrum) | korelasi terhadap kandidat memakai kode penerima dan merusak jaminan tuduhan salah Tardos |
| Registri menyimpan kode | registri menyimpan komitmen (`code_digest`); kode diturunkan ulang dari rahasia kode | siapa pun yang dapat membaca kode dapat memfitnah penerima |
| Kanari DOCX lewat referensi font eksternal | relasi gambar eksternal | Word tidak mengambil font eksternal |
| Banyak simbol lebar-nol di akhir kata | paling banyak dua simbol per posisi (sebelum dan sesudah kata), dari alfabet berbeda | MuPDF dan poppler membuang glif identik yang ditumpuk di posisi yang sama (dianggap tebal palsu) |
| Ambang Z ditetapkan sebelum analisis | aturan ambang ditetapkan saat penerbitan; nilai Z dihitung setelah dekode dari posisi yang benar-benar terbaca, sebelum skor dihitung | kanal yang rusak menghapus posisi; ambang tetap untuk pembacaan penuh akan terlalu ketat untuk bukti parsial. Aturannya tetap dan tidak pernah melihat kode salinan yang dinilai (tahap 1 tidak melihat kode penerima mana pun; tahap lanjutan pelacakan bertahap hanya melihat kode salinan yang sudah dituduh), sehingga tidak dapat disesuaikan setelah melihat hasil |
| Konstanta "Skoric 2006, 2 pi^2" | dipertahankan sebagai bawaan, atribusi dikoreksi | 2 pi^2 berasal dari Skoric, Vladimirova, Celik, dan Talstra untuk skor asimetris (pendekatan Gauss). Dengan skor simetris konstanta asimtotiknya pi^2/2, jadi ada margin sekitar 4 kali. Untuk c kecil kecukupannya kini dihitung langsung: batas terbukti peluang koalisi lolos paling besar 5 x 10^-17 untuk c = 2 sampai 5 (eps = 10^-6, N paling sedikit 20, pembacaan penuh; [batas deteksi terbukti](#batas-deteksi-terbukti)). Jaminan tuduhan salah tidak bergantung pada K karena berasal dari ambang Chernoff |

## Referensi

1. G. Tardos. Optimal probabilistic fingerprint codes. Proc. 35th ACM STOC, 2003, hlm. 116-125. Versi jurnal: J. ACM 55(2), 2008.
2. B. Skoric, T. U. Vladimirova, M. Celik, J. C. Talstra. Tardos fingerprinting is better than we thought. IEEE Trans. Inf. Theory 54(8):3663-3676, 2008. arXiv:cs/0607131.
3. B. Skoric, S. Katzenbeisser, M. U. Celik. Symmetric Tardos fingerprinting codes for arbitrary alphabet sizes. Des. Codes Cryptogr. 46(2):137-166, 2008. IACR ePrint 2007/041.
4. T. Laarhoven, B. de Weger. Optimal symmetric Tardos traitor tracing schemes. Des. Codes Cryptogr. 71(1):83-103, 2014. arXiv:1107.3441.
5. J. T. Brassil, S. Low, N. F. Maxemchuk. Copyright protection for the electronic distribution of text documents. Proc. IEEE 87(7), 1999 (pergeseran baris dan kata).
6. M. Tancik, B. Mildenhall, R. Ng. StegaStamp: Invisible hyperlinks in physical photographs. CVPR 2020.
7. M. Delbracio, D. Kelly, M. S. Brown, P. Milanfar. Mobile computational photography: a tour. Annu. Rev. Vis. Sci. 7, 2021. arXiv:2102.09000 (bagian 3.3.3: HDR+ menggabung 2 sampai 8 bingkai yang sengaja kurang terang).
8. S. W. Hasinoff dkk. Burst photography for high dynamic range and low-light imaging on mobile cameras. ACM Trans. Graph. 35(6), 2016.
9. AOSP, metadata kamera Android (`camera/docs/metadata_definitions.xml`): `android.jpeg.quality` ("85-95 is typical usage range", juga untuk HEIC) dan `android.sensor.noiseProfile` (N(x) = sqrt(S x + O)).
10. A. Foi, M. Trimeche, V. Katkovnik, K. Egiazarian. Practical Poissonian-Gaussian noise modeling and fitting for single-image raw-data. IEEE Trans. Image Process. 17(10), 2008.
11. K. He, J. Sun, X. Tang. Guided image filtering. IEEE TPAMI 35(6), 2013.
12. M. Zhang, B. K. Gunturk. Multiresolution bilateral filtering for image denoising. IEEE Trans. Image Process. 17(12), 2008.
13. F. Cao, F. Guichard, H. Hornung. Dead leaves model for measuring texture quality on a digital camera. Proc. SPIE 7537, 2010.
14. IEEE 1858-2016, Camera Phone Image Quality (metrik kehilangan tekstur).
15. F. Durand, J. Dorsey. Fast bilateral filtering for the display of high-dynamic-range images. ACM Trans. Graph. 21(3), 2002.
16. Imatest, dokumentasi Sharpening (imatest.com/docs/sharpening).
17. Steam Hardware and Software Survey, September 2026 (store.steampowered.com/hwsurvey).
18. IEC 61966-2-1:1999, sRGB.
19. ITU-R BT.1886, EOTF acuan layar datar.
20. Trilux, pencahayaan kantor dan stasiun kerja layar: batas luminans menurut EN 12464-1.
21. RTINGS, uji sudut pandang monitor (rtings.com/monitor/tests/picture-quality/viewing-angle).
22. G. Westheimer. Visual acuity and hyperacuity. Dalam Handbook of Optics, ed. ke-3, vol. III, bab 4. McGraw-Hill, 2010.
23. G. Westheimer, S. P. McKee. Spatial configurations for visual hyperacuity. Vision Res. 17(8):941-947, 1977.
24. S. L. Groll, J. Hirsch. Two-dot vernier discrimination within 2.0 degrees of the foveal center. J. Opt. Soc. Am. A 4(8):1535-1542, 1987.
25. J. Brassil, S. Low, N. Maxemchuk, L. O'Gorman. Electronic marking and identification techniques to discourage document copying. Proc. IEEE INFOCOM 1994, hlm. 1278-1287 (garis dasar teks cetak bernilai bulat, satu piksel printer).
26. C.-L. Chen, G. T.-C. Chiu, J. P. Allebach. Robust spatial-sampling controller design for banding reduction in electrophotographic process. J. Imaging Sci. Technol. 50(6):530-536, 2006.
