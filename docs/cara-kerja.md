# Cara kerja TAPAK

[Kembali ke README](../README.md) · [Operasi](operasi.md) · [Keamanan dan batasan](keamanan.md)

## Lima kanal, ditambah satu kanal pilihan

Kode penerima yang sama ditanam di empat kanal, ditambah token kanari sebagai kanal kelima. Kanal keenam, pilihan kata, hanya dipakai bila penerbit memilihnya dan meninjau setiap titiknya ([rinciannya di bawah](#kanal-pilihan-kata-opsional)). Kanal mana pun boleh rusak; dekoder menggabungkan apa yang tersisa.

| Kanal | Yang ditanam | Kebocoran yang ditangani |
|---|---|---|
| 1. Geser kata dan baris | kelompok kata bergeser horizontal dan baris bergeser vertikal sebesar 0,05 mm. Bit dikodekan relatif terhadap tetangga (kontrol, data, kontrol), sehingga sisa distorsi perspektif saling meniadakan | cetak, foto, tangkapan layar |
| 2. Pola latar | pola acak berfrekuensi rendah +/-2 tingkat abu-abu (sel 2 mm). Setiap posisi kode menempati 8 sel yang tersebar dan didekode secara buta per bit | tangkapan layar, foto layar |
| 3. Karakter tak terlihat | sepasang simbol lebar-nol sebelum dan sesudah kata (2 bit per simbol) serta huruf kembar Kiril pada kata huruf kecil | salin-tempel, berkas diteruskan |
| 4. Varian semantik | parafrasa kalimat pembuka, penutup, dan tembusan oleh LLM lokal, disetujui manusia | pengetikan ulang, tetapi hanya beberapa bit (4 pada contoh), belum cukup untuk menyebut nama |
| 5. Kanari DNS | satu subdomain unik per salinan di bawah domain kanari. Pendengar DNS mencatat kapan nama itu dicari dan resolver mana yang bertanya, bukan siapa pembukanya. Token ini tidak membawa kode Tardos | berkas dibuka di luar jaringan satuan, di Adobe Reader atau Word |
| 6. Pilihan kata (opsional) | bentuk bermakna sama dari tabel leksikon draf, misalnya "terdiri atas" atau "terdiri dari", "dan" atau "serta". Setiap titik disetujui manusia | pengetikan ulang oleh satu pembocor, bila dokumennya cukup panjang (terukur: mulai sekitar 1.300 kata isi; TAPAK menyatakan cukup mulai 64 bit, sekitar 1.800 kata isi); tidak tahan kolusi. Bentuknya terlihat di kertas, jadi dapat ditiru |

## Dokumen induk hasil pindai

Halaman hasil pindai tidak memiliki lapisan teks untuk digambar ulang, jadi tandanya dibuat langsung di piksel gambar halaman (`tapak/marker/raster.py`). Rencana penandaan, posisi kode, kunci, dan kode Tardos sama dengan halaman teks.

* **Deteksi per halaman.** Halaman dianggap hasil pindai bila isi yang terlihat hanya satu gambar yang menutupi hampir seluruh halaman. Teks di atasnya boleh tidak ada atau tak terlihat (lapisan OCR, mode render 3). Halaman lain tetap memakai jalur teks, jadi dokumen campuran ditangani per halaman.
* **Kotak kata.** Tesseract (bahasa `ind`, mesin LSTM, satu utas, resolusi dinyatakan) membaca gambar halaman induk satu kali. Kotak kata dan barisnya menjadi baris, kata, dan kelompok geser seperti pada halaman teks. Catatan penerbitan dan registri hanya menyimpan hash daftar kotak itu dan versi Tesseract, tanpa kotak, kata, atau gambar.
* **Geser.** Tinta kelompok data bergeser 0,05 mm (0,59 piksel pada 300 dpi) dengan interpolasi kubik subpiksel, lalu dicampur lewat masker lunak yang hanya mencakup tinta dan 2 piksel di sekitarnya. Tekstur kertas di sekitar kata tidak ikut diinterpolasi, sehingga tidak ada tepi petak atau lingkaran cahaya. Piksel yang ditinggalkan tinta mengambil kertas di sebelahnya dari gambar induk. Baris data bergeser vertikal dengan cara yang sama.
* **Pola latar.** Pola berkunci +/-2 tingkat abu-abu ditambahkan hanya ke piksel kertas, yaitu piksel yang paling banyak 20 tingkat lebih gelap dari warna kertas halaman itu, pada resolusi gambar halaman. Dekoder memakai batas yang sama untuk menyisihkan tinta.
* **Kanal lain.** Kanari tetap dipasang karena berupa aksi PDF. Karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di halaman pindaian, dan rencana penandaan menyatakannya.
* **Salinan.** Gambar halaman bertanda menggantikan gambar induk sebagai Flate tanpa kehilangan data, dengan ukuran dan letak yang sama. Lapisan OCR tak terlihat dari induk tidak ikut ke salinan, karena berisi kata dokumen induk tanpa tanda.
* **Gerbang.** Salinan tanpa tanda harus identik piksel demi piksel dengan gambar halaman induk. Setiap salinan bertanda hanya boleh berubah di sekitar tinta yang digeser dan, di kertas, sebesar pola latar (-4 sampai +2 tingkat). Bila tidak, penerbitan berhenti.
* **Pelacakan.** Templat dekoder adalah gambar halaman induk itu sendiri. Kotak kata dibaca ulang dengan panggilan Tesseract yang sama dan hanya dipakai bila hash-nya sama dengan catatan penerbitan. Bila berbeda, misalnya karena versi Tesseract lain, kanal geser halaman pindaian ditolak dengan catatan, dan pola latar tetap dibaca. Slot geser halaman pindaian ditempatkan setelah semua halaman teks, sehingga perubahan kotak kata tidak pernah menggeser posisi kode halaman teks. Ambang dan aturan tuduhan tidak berubah.

Angka terukurnya ada di [batasan 8](keamanan.md#batasan).

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
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), attacks, simulate
  marker/       layout, master (font), plan, pdf_shift, background, pdf_zerowidth, semantic, lexical,
                canary, docx_marker, render (gambar ulang + gerbang visual), raster (halaman pindaian),
                issue (paralel)
  decoder/      rectify, lines (Tesseract), ch_shift, ch_background, ch_zerowidth, ch_semantic, ch_lexical,
                ch_docx, image, fuse, accuse, trace, report (berita acara)
  assets/       font DejaVu, leksikon pilihan kata (leksikon/naskah_dinas_v1.json, draf)
  registry/     chain (rantai hash, trigger tambah-saja), signing (Ed25519), verify, merkle
  canary_dns/   server (dnslib), store (log berantai)
  llm/          provider (antarmuka), mock (deterministik), llamacpp (lokal, loopback saja)
  learned_wm/   kerangka tanda air berbasis model (opsional, belum dilatih)
  web/          FastAPI + HTMX, antarmuka berbahasa Indonesia
  photos.py     simulator degradasi foto dan tangkapan layar
  ketik.py      simulator pengetikan ulang dan OCR (untuk pengujian dan pengukuran)
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
research/ketik/ pengukuran kanal pilihan kata (kapasitas, galat baca, atribusi)
research/pindaian/ pengukuran induk hasil pindai (protokol, hasil, potongan gambar)
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
| Kumpulan foto sintetis (`make photos` lalu `make bench`): 32 foto bersudut 0 sampai 30 derajat dan 8 tangkapan layar dari 4 salinan (halaman 1), dikompresi JPEG dua kali seperti WhatsApp. Simulator tidak memodelkan printer, jadi pola latar tetap utuh | 39 dari 40 benar, 1 "tidak cukup bukti" (foto dengan 95 % kertas jenuh putih), 0 tuduhan salah |
| 10 foto sintetis bersudut sampai 30 derajat | 10 dari 10 benar |
| Halaman gabungan digital: setengah atas salinan A, setengah bawah salinan B (2 pasangan) | penerima A dan B dituduh, tidak ada orang lain |
| Teks salinan disalin-tempel (MuPDF dan poppler) | kode utuh, salinan teridentifikasi |
| Teks diketik ulang dengan 5 % salah ketik (kanal semantik) | 4 bit semantik pulih 20 dari 20 percobaan; tidak cukup untuk menyebut nama |
| Teks diketik ulang, kanal pilihan kata ([rincian](#kanal-pilihan-kata-opsional)): dokumen sintetis 6 halaman (47 bit), 200 percobaan untuk N = 20 dan 200 untuk N = 100, pelacakan pertama yang tercatat | 395 dari 400 benar, 0 tuduhan salah; nota dinas contoh 2 halaman (11 bit): "tidak cukup bukti" |
| Dokumen induk hasil pindai (nota dinas sintetis 2 halaman, 300 dpi), 20 salinan: PDF salinan, tangkapan layar, dan foto sintetis halaman 1 ([rincian](keamanan.md#batasan)) | 60 dari 60 benar, 0 tuduhan salah; gabungan sepertiga halaman dari 3 salinan: 15 dari 15 anggota koalisi tertangkap, tidak ada orang lain |
| Penerbitan 20 salinan dokumen 2 halaman | sekitar 4 sampai 5 detik (hasil pindai 300 dpi: sekitar 30 detik) |
| Kanari DNS, pembukaan disimulasikan (kueri langsung ke pendengar lokal) | tercatat dalam sekitar 0,1 detik (syarat: di bawah 5 detik) |
| Registri: verifikasi hanya dengan kunci publik, setiap perubahan baris terdeteksi | lulus |
| `make demo` (skenario lengkap) | sekitar 15 detik |

## Kanal pilihan kata (opsional)

Pengetikan ulang menghapus semua tanda kecuali isi kata-katanya. Kanal ini memberi setiap salinan pilihannya sendiri di antara bentuk yang bermakna sama dalam naskah dinas, misalnya "sehubungan dengan" atau "berkenaan dengan", "terdiri atas" atau "terdiri dari", "dan" atau "serta" di antara dua kata biasa. Kanal ini tidak aktif kecuali penerbit memilihnya dan meninjau setiap titiknya (`tapak leksikal` atau halaman Terbitkan, lihat [operasi](operasi.md#kanal-pilihan-kata-opsional)). Tanpa itu, penerbitan, catatan penerbitan, dan registri sama persis dengan sebelumnya.

* **Tabel leksikon.** Bentuk-bentuknya ada di `tapak/assets/leksikon/naskah_dinas_v1.json` (versi 1). Tabel ini masih **draf** dan belum disahkan peninjau bahasa Tata Naskah Dinas. Versi dan digest tabel dicatat di berkas tinjauan, catatan penerbitan, dan registri. Bentuk dalam satu aturan berbeda sedikitnya 3 karakter, dan tidak ada bentuk yang sama dengan bentuk lain dikurangi satu kata. Dengan begitu, salah ketik atau kata yang terlewat tidak mengubah satu bentuk menjadi bentuk lain.
* **Yang tidak pernah diubah.** Angka, nama, satuan, jabatan, waktu, koordinat, bilangan, perintah, larangan, tenggat, dan kata ingkar tidak pernah diubah. Frasa ditolak bila frasa itu sendiri, atau kata dalam jarak dua kata di kalimat yang sama, termasuk salah satunya. Ungkapan tetap seperti "dan lain-lain", "namun demikian", atau "untuk mereka" juga ditolak. Judul paragraf (juga "14. Maksud dan tujuan."), kepala surat, tanda tangan, tembusan, kaki halaman, dan kalimat kanal semantik tidak disentuh; tanda tangan, tembusan, dan kaki halaman juga tidak dihitung sebagai kata isi. Pemindaian hanya melaporkan jumlah penolakan per kategori, tanpa kata dokumen.
* **Tata letak.** Setiap kombinasi bentuk pada satu baris harus muat kembali di baris yang sama: tepi kiri dan kanan tetap, label "1.", "14." atau "a." dan kata pertama sesudahnya tetap di tempatnya (label dikenali dari bentuknya dan kolom teksnya, bukan dari lebar celahnya), jarak antarkata 1 sampai 3 spasi. Kata lain di baris itu digambar dengan glifnya sendiri dan tetap membawa karakter tak terlihat serta huruf kembarnya. Baris itu keluar dari kanal geser. Pada nota dinas contoh, kanal geser turun dari 183 menjadi 140 bit; pada surat telegram, dari 97 menjadi 84.
* **Peninjauan.** Setiap titik disetujui atau ditolak manusia, dengan melihat seluruh kalimatnya (lintas baris) dan frasanya dalam kurung siku. Penerbitan diblokir selama masih ada titik yang menunggu. Titik dan bentuk yang disunting di luar TAPAK ditolak, karena digest pemindaiannya tidak cocok dan pemindaian ulang dokumen induk memberi titik yang berbeda. Keputusan setuju atau tolak di berkas itu tidak diautentikasi: berkas yang statusnya disunting tangan tetap diterima, jadi `leksikal.json` dijaga seperti dokumen induk.
* **Posisi kode.** Dokumen yang memakai kanal ini mengambil posisi kanal semantik dan pilihan kata hanya dari posisi dengan bias 0,3 sampai 0,7. Keduanya memakai satu urutan berkunci: semantik dari depan, pilihan kata dari belakang. Penerbitan ditolak bila pita itu tidak cukup untuk semua bit keduanya (misalnya c = 1 dengan dokumen panjang), jadi posisinya tidak pernah bertabrakan atau berulang. Aturan ini dicatat sebagai `retype_positions` di catatan penerbitan dan registri; dokumen lama tetap memakai aturan seragam. Pemilihan hanya memakai vektor bias, tidak pernah kode penerima, jadi ambang Chernoff tetap berlaku. Di dekat p = 1/2, satu pembocor menyumbang skor sampai 1 per bit. Sebaliknya, koalisi yang memilih bit minoritas menekan skornya ke sekitar nol, jadi posisi ini hanya menolong untuk pembocor tunggal.
* **Dekode.** Teks bukti disejajarkan dengan teks induk (jarak edit), lalu setiap bentuk dicocokkan bersama konteks 16 karakter di kiri dan kanannya. LLR = 2 x selisih jarak edit, paling besar 6, dan paling besar 2 bila suntingan berkumpul di frasa itu. Frasa yang ditulis ulang atau terpotong dianggap tidak terbaca, bukan dibaca salah. Pengecualiannya titik berkonteks berulang: frasa dan konteksnya juga ada di bagian lain dokumen. Bila pembocor menukar urutan kalimat, titik itu dapat terbaca di tempat lain dengan yakin. Akibatnya skor pembocor turun, tetapi salinan lain tidak pernah tertuduh karenanya. Pemindaian menandai titik seperti ini untuk peninjau; kedua contoh tidak memilikinya. Ambangnya tetap dihitung dari vektor bias dan bobot dekoder.
* **Tanda yang terlihat.** Pilihan kata dan varian kalimat terlihat di kertas. Bila sebuah nama hanya didukung kedua kanal itu (tanpa keduanya salinan itu tidak mencapai ambang), hasil CLI, web, dan berita acara menambahkan peringatan di bawah putusan: siapa pun yang pernah membaca salinan itu dapat meniru pilihan katanya saat mengetik ulang, jadi hasil itu menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan memerlukan bukti pendukung. Peringatan ini tidak mengubah ambang atau putusan.

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
