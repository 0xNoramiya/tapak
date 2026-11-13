# Foto ponsel sungguhan dari halaman contoh yang dicetak

Sampai 12 November 2026 setiap foto dan cetakan uji TAPAK sintetis ([batasan 10](../../docs/keamanan.md#batasan-10)). Hari itu tim mencetak halaman 1 surat telegram contoh dengan printer sungguhan dan memotretnya dengan dua ponsel: 13 berkas foto dari lima keadaan lembar. Satu berkas (blur/175633) ternyata potongan galeri dari foto lain (miring/175559), jadi pengambilan gambarnya 12.

| Keadaan lembar | Foto | Ponsel |
|---|---|---|
| datar, difoto miring | 3 | vivo 1935 (3264 x 1836) |
| datar, foto buram | 2 | vivo 1935 (3264 x 1836 dan 2368 x 1328) |
| sobek menjadi empat, disusun kembali | 3 | iPhone 11 (4032 x 2268) |
| kusut diremas, diratakan kembali | 2 | iPhone 11 |
| basah (bernoda air, bergelombang) | 3 | iPhone 11 |

Foto tidak ada di repositori: selain halaman contoh fiktif, terlihat meja dan ruangan. Yang disimpan hanya angka: `hasil/foto.jsonl` (satu baris per foto), `hasil/geser.json`, dan `hasil/medan.json` (bentuk setiap lembar, lihat di bawah). `ukur.py` mengulang semuanya dari folder foto.

**Lembar itu dokumen induk tanpa tanda.** Tim mencetak berkas contoh dari folder `samples/` repositori (`surat_telegram.pdf`), bukan salinan terbitan; ini baru diketahui setelah pengukuran selesai. Studi ini karena itu menjawab tiga hal: apakah halaman ditemukan, apakah ada yang tertuduh padahal tidak ada salinan yang bocor, dan seberapa jauh cetakan dan kertas sungguhan menggeser kata tanpa tanda apa pun, yaitu derau yang harus dilampaui sebuah tanda. **Apakah salinan yang benar disebut dari cetakan sungguhan belum terjawab** dan menunggu cetakan dari salinan yang diketahui ([yang berikutnya](#yang-berikutnya)).

## Hasil utama: cetakan sungguhan dari salinan yang diketahui

Setelah foto pertama itu, tim mencetak tiga salinan yang penerimanya hanya diketahui studi, kedua halaman masing-masing, dengan printer sungguhan yang sama, dan memotret setiap lembar rata dengan iPhone 11 (12 megapiksel, halaman pada sekitar 330 dpi): 18 foto. `salinan.py` melacak setiap foto terhadap penerbitannya, sekali lagi setelah foto itu diperkecil seperti kiriman aplikasi pesan (sisi panjang 1600 px, JPEG kualitas 75 dua kali, sekitar 130 dpi), dan sekali terhadap penerbitan lain (`hasil/salinan.jsonl`; `hasil/salinan_tanpa_medan.jsonl` menyimpan foto yang sama dengan dekoder sebelum [medan lokal](#medan-lokal-kelompok-kata)).

| Salinan | Foto asli: disebut benar (skor / ambang) | Setelah aplikasi pesan | Bit latar salah, hal. 1 / hal. 2 | Bit kata salah | Bit baris salah |
|---|---|---|---|---|---|
| A: skema v2, profil latar bawaan (253 +/- 2) | 6 dari 6 (3,3 sampai 4,1) | 6 dari 6 (3,8 sampai 4,1) | 19,8 % / 8,3 % | 16 % (sebelum medan lokal 25 %) | 0 dari 63 |
| B: skema v2, profil latar cetak (242 +/- 5) | 6 dari 6 (4,5 sampai 4,6) | 6 dari 6 (4,6 sampai 4,7) | 1,9 % / 0,1 % | 22 % (sebelumnya 25 %) | 3 dari 60 |
| C: skema v1, profil latar bawaan | 6 dari 6 (3,1 sampai 3,8) | 6 dari 6 (3,7 sampai 3,9) | 19,2 % / 8,6 % | 5,3 % | 4 dari 63 |

* **36 dari 36 pelacakan menyebut salinan yang benar**, dari satu foto satu halaman, dan tidak satu pun menyebut orang lain (skor orang lain paling tinggi 0,51 kali ambang).
* **Terhadap penerbitan lain tidak ada yang tertuduh**: 0 dari 18 (paling tinggi 0,34 kali ambang). Salinan di sana punya kode lain di bawah vektor bias yang sama.
* **Pola latarlah yang membawa pelacakan di kertas.** Dengan kanal latar saja 18 dari 18 disebut. Dengan kanal geser saja 3 dari 18: ketiga foto halaman 1 salinan A (1,17 sampai 1,18 kali ambang), sejak dekoder membaca kelompok kata terhadap [medan lokal](#medan-lokal-kelompok-kata); sebelum itu 0 dari 18 (paling dekat 0,97). Halaman 1 salinan B berhenti di 0,87 sampai 0,88, halaman 2 yang pendek dan skema v1 jauh di bawah ambang. Bit kata skema v1 (geser dua kali lebih besar) 5,3 % salah, tetapi posisinya terlalu sedikit.
* **Printer ini mencetak pola profil bawaan.** Simulator kami mengasumsikan tingkat abu-abu di atas sekitar 250 tercetak sebagai kertas polos, sehingga pola bawaan (251 sampai 255) hilang di kertas. Pada printer ini pola itu tercetak dan terbaca, dengan seperlima bitnya salah di halaman penuh teks. Profil cetak terbaca hampir tanpa galat. Jadi di kertas profil bawaan bergantung pada printer; profil cetak pilihan yang kuat.
* **Foto yang diperkecil tidak lebih buruk.** Bit latar profil bawaan malah lebih sedikit salah setelah diperkecil (11 sampai 13 % di halaman 1), dan pelacakannya 4 detik, bukan 30 sampai 45.

Batasnya: satu printer (tipe belum dicatat), satu ponsel, lembar baru yang rata dan difoto tegak lurus, satu dokumen, tiga salinan. Lembar kusut, basah, atau sobek dari salinan bertanda, printer lain, dan mode hemat toner belum diuji.

## Halaman tidak ditemukan

Dengan registrasi sebelum studi ini, 12 dari 13 foto dijawab "halaman dokumen induk tidak ditemukan", juga foto iPhone yang tajam dan hampir tegak lurus dari lembar yang hampir rata. Pose awalnya benar: SIFT dan kontur menemukan halaman 1 pada 130 sampai 270 dpi. Yang gagal adalah ambang korelasi ECC 0,75: korelasi bidang datar hanya 0,42 sampai 0,70 (satu foto 0,80).

Pada foto yang diperiksa blok demi blok (basah/G_3332), setelah homografi terbaik bagian halaman masih meleset 1,2 mm dan lebih, berbeda arah di bagian yang berbeda, sedangkan hampir setiap blok cocok dengan induk (0,8 sampai 0,95) setelah digeser sendiri. Kertas sungguhan tidak datar, dan lensa ponsel membengkokkan garis lurus. Foto simulasi kami datar sempurna (korelasi 0,92 ke atas pada 40 foto set contoh), jadi kegagalan ini tidak pernah muncul.

## Langkah halaman tidak datar

`rectify.estimate_bend` ([cara kerja](../../docs/cara-kerja.md#registrasi-bukti-gambar)) mengukur sisa itu blok demi blok dan membuat dua medan geser dari pengukuran yang sama: medan halus untuk menjawab "apakah ini halaman induk?" dengan ambang 0,75 yang sama, dan medan mulus (rata-rata 15 mm) untuk meluruskan gambar yang dibaca dekoder.

| Foto | Lembar | Ponsel | Korelasi bidang datar | Setelah medan | Ditemukan | dpi efektif | Posisi terbaca | Skor tertinggi / ambang |
|---|---|---|---|---|---|---|---|---|
| basah/G_3332 | basah | iPhone 11 | 0,63 | 0,92 | ya | 246 | 176 | 0,24 |
| basah/G_3337 | basah | iPhone 11 | 0,53 | 0,90 | ya | 262 | 122 | 0,19 |
| basah/G_3338 | basah | iPhone 11 | 0,53 | 0,91 | ya | 255 | 119 | 0,23 |
| blur/175633 | buram | vivo 1935 | 0,70 | 0,84 | ya | 160 | 163 | 0,17 |
| blur/175737 | buram | vivo 1935 | - | - | tidak | - | - | - |
| kusut/G_3339 | kusut | iPhone 11 | 0,54 | 0,82 | ya | 250 | 107 | 0,16 |
| kusut/G_3341 | kusut | iPhone 11 | 0,59 | 0,83 | ya | 212 | 112 | 0,23 |
| miring/175559 | datar, miring | vivo 1935 | 0,69 | 0,83 | ya | 160 | 160 | 0,11 |
| miring/180037 | datar, miring | vivo 1935 | 0,46 | 0,55 | tidak | - | - | - |
| miring/180124 | datar, miring | vivo 1935 | 0,80 | 0,86 | ya | 134 | 147 | 0,12 |
| sobek/G_3334 | sobek | iPhone 11 | 0,42 | 0,84 | ya | 235 | 79 | 0,19 |
| sobek/G_3335 | sobek | iPhone 11 | 0,56 | 0,88 | ya | 216 | 123 | 0,45 |
| sobek/G_3336 | sobek | iPhone 11 | 0,55 | 0,88 | ya | 238 | 124 | 0,44 |

* **Seberapa tidak datar.** Medan halus yang terukur paling jauh 1,9 sampai 4,6 mm dari bidang datar (lembar kusut paling sedikit: lipatannya kecil-kecil, bukan lengkung besar).
* **Ditemukan: 1 menjadi 11 dari 13.** Dua sisanya foto yang sangat buram: satu kabur gerak (korelasi 0,55 setelah medan), satu difoto dari jauh sehingga teksnya tidak terbaca (ECC tidak konvergen). Jawaban "tidak ditemukan" di sana benar.
* **Dokumen lain tidak ikut lolos.** Foto yang sama terhadap nota dinas contoh (font, tepi, dan kepala halaman yang sama): korelasi bidang datar paling tinggi 0,32 dan setelah medan paling tinggi 0,40 (medan hanya dicoba bila pose belum dibuang pada tingkat ECC kasar). Tiga foto simulasi nota dinas dari set contoh terhadap surat telegram (pemeriksaan sekali jalan, tidak di `hasil/`): 0,54 sampai 0,58, tanpa kenaikan dari medan.
* **Tidak ada yang tertuduh.** Setiap foto dilacak terhadap penerbitan surat telegram itu (20 salinan, skema v2, dibuat untuk studi ini): 13 dari 13 "tidak cukup bukti", skor tertinggi paling besar 0,45 kali ambang. Itu jawaban yang benar: lembar induk tidak membawa kode siapa pun.
* **Sebagian lembar juga ditemukan.** Empat foto (basah, datar, sobek, kusut) dipotong menjadi separuh atas, 40 % tengah, dan separuh bawah lembar: 12 dari 12 potongan ditemukan (korelasi 0,84 sampai 0,95), lewat fitur atau kata Tesseract lalu langkah halaman tidak datar (pemeriksaan sekali jalan, tidak di `hasil/`).
* **Setelah lewat aplikasi pesan juga ditemukan.** Ke-13 foto diperkecil ke sisi panjang 1600 px dan dikompresi JPEG kualitas 75 dua kali (dikirim lalu diteruskan): 11 yang sama ditemukan (korelasi 0,83 sampai 0,92 pada 66 sampai 108 dpi efektif), masing-masing dalam 4 sampai 6 detik; dua foto buram yang sama tetap ditolak (pemeriksaan sekali jalan).
* **Kertas sungguhan tidak terbaca sebagai pola latar.** Ke-13 foto lembar tanpa tanda itu juga dilacak terhadap penerbitan profil latar cetak: pola tidak ditemukan pada satu pun (uji pilot z antara -0,3 dan 1,9), tidak ada bit latar yang dipakai, dan tidak ada yang tertuduh (skor tertinggi paling besar 0,42 kali ambang). Tekstur kertas, bayangan, noda air, dan lipatan tidak meniru pola itu (pemeriksaan sekali jalan).
* **Foto simulasi tidak berubah.** Langkah ini hanya berjalan bila korelasi bidang datar di bawah 0,90; benchmark README terulang byte demi byte (`make bench-check`).

## Seberapa teliti posisi kata terukur

`ukur.py geser` membaca geseran setiap kelompok kata (pengukuran dekoder geser sendiri) dan membandingkannya antarfoto.

* **Kamera cukup teliti.** Tiga pasang foto iPhone memotret lembar yang sama dalam keadaan yang sama (basah, kusut, sobek). Setelah bentuk kertas dibuang (butir ketiga), geseran kelompok kata pada kedua foto hampir sama: korelasi 0,92 sampai 1,00 pada dx dan 0,75 sampai 0,94 pada dy. Bagian yang berbeda antara dua foto, yaitu derau kamera, hanya 0,01 sampai 0,03 pt (3 sampai 10 um) pada lembar basah dan sobek dan 0,05 sampai 0,06 pt pada lembar kusut, di bawah geser skema v2 (0,071 pt, 25 um).
* **Kertasnya yang bergerak.** Setelah medan mulus registrasi dan gangguan baris (geser dan kemiringan per baris) dibuang, kelompok kata masih meleset 0,13 sampai 0,30 pt pada lembar datar, basah, dan sobek, dan 0,32 sampai 0,36 pt pada lembar kusut: dua sampai lima kali geser v2. Pada dy, yang tidak membawa tanda kata, besarnya sama, jadi itu bentuk kertas, bukan tanda.
* **Baris tetangga meramalkan sebagian besar bentuk itu.** Bila geseran setiap kelompok diramal dari kelompok di baris lain di dekatnya (kernel Gauss, baris sendiri tidak ikut), sisa pada dy turun menjadi 0,05 sampai 0,06 pt pada lembar basah dan sobek (iPhone), 0,07 sampai 0,09 pt pada lembar datar (vivo), dan 0,19 sampai 0,22 pt pada lembar kusut (kernel 8 mm sepanjang baris dan 4 mm antarbaris, yang menyisakan paling sedikit pada dy); pada dx sisanya 0,07 sampai 0,12 pt, dan 0,22 sampai 0,25 pt pada lembar kusut. Sisa itu juga melekat pada lembar, bukan pada foto. Karena lembarnya tanpa tanda, seluruhnya derau cetakan: bentuk kertas yang lebih halus dari jarak baris dan letak glif printer. Dekoder sekarang memakai satu polinomial derajat 3 per halaman dan melaporkan sigma kata 0,08 sampai 0,12 pt pada foto ini, di atas geser v2.

* **Dugaan saat itu: batas fisik, bukan kekurangan dekoder** (dikoreksi di bagian berikut). Kelompok geser skema v2 hampir semuanya satu kata (229 kata terukur per kata, 228 kelompok pada halaman ini), jadi tidak ada pengukuran yang lebih rapat yang dapat memisahkan bentuk kertas dari tanda. Sisa 0,07 sampai 0,12 pt pada dx itu seukuran kisi letak printer 600 dpi: satu piksel perangkat 42 um, dan pembulatan letak kata ke piksel utuh saja sudah memberi sekitar 0,035 pt per kata. Tanda 25 um berada di dalam derau itu.

Kesimpulan saat itu: pada cetakan sungguhan tanpa tanda, kelompok kata sudah bergeser 0,07 sampai 0,12 pt pada arah tanda (dx) setelah bentuk kertas diramal dari baris tetangga, sebesar atau lebih besar dari geser kata v2 (0,071 pt, 25 um). Cetakan salinan yang diketahui kemudian menunjukkan bahwa "batas fisik" di atas terlalu cepat disimpulkan: sebagian besar sisa itu bukan derau, dan dekoder dapat membuang sebagiannya (bagian berikut).

## Medan lokal kelompok kata

Cetakan salinan yang diketahui menjawab pertanyaan yang tidak dapat dijawab lembar tanpa tanda: dari mana seperempat bit kata yang salah itu? Geseran setiap kelompok kata halaman 1 salinan A dan B (enam foto, 204 kelompok) dikurangi tandanya yang diketahui, medan polinomial halaman, dan gangguan baris. Sisanya 0,09 sampai 0,10 pt, lebih besar dari tanda (0,071 pt), dan sisa itu:

* **melekat pada lembar.** Korelasinya 0,998 sampai 0,999 antara tiga foto lembar yang sama. Derau kamera tidak berperan.
* **sebagian besar sama pada kedua lembar.** Korelasinya 0,78 sampai 0,81 antara salinan A dan B, dua cetakan dengan tanda berbeda, pada kelompok yang tandanya sama maupun yang berlawanan. Jadi bukan pembulatan letak kata ke kisi printer (itu akan bergantung pada tanda), dan bukan derau acak per cetakan.
* **bukan buatan dekoder.** Cetakan dan foto simulasi dari salinan yang sama menyisakan 0,011 sampai 0,012 pt, tanpa pola itu.
* **berupa medan yang berubah dalam kira-kira satu sentimeter.** Sisa satu kelompok dapat diramal dari kelompok di baris lain di dekatnya, dan medan halus registrasi (blok 6,5 mm, sebelum dirata-ratakan 15 mm) berkorelasi 0,83 sampai 0,87 dengannya. Geseran tegak lurus baris (dy) tidak meramalkannya, jadi bukan paralaks lembar yang tidak rata. Pembulatan lebar glif pada 300 sampai 1200 dpi juga tidak (korelasi paling tinggi 0,3), dan kata yang sama di tempat lain bergeser lain.

Cetakan printer ini sendiri bergeser secara lokal, hampir sama pada setiap lembar, dan gangguan baris (geser dan kemiringan) terlalu kaku untuk mengikutinya. Penyebabnya di dalam printer belum diketahui.

**Perbaikan dekoder** (`ch_shift.local_field` dan `choose_local_field`). Pada bukti gambar, setiap kelompok kata skema v2 kini juga dibaca terhadap rata-rata berkernel Gauss dari geseran kelompok di baris lain di dekatnya. Baris sendiri tidak ikut, jadi tanda baris itu tidak ikut terhapus. Lebar kernel dipilih per halaman dari bukti saja: dari 6, 9, 13, dan 20 mm, yang medannya menyisakan paling sedikit setelah garis sepanjang setiap baris dibuang (gangguan baris yang memang diproyeksikan keluar oleh dekoder). Medan dari kira-kira sepuluh tetangga membawa sepersepuluh sebaran mereka sendiri, jadi medan hanya dipakai bila menjelaskan paling sedikit seperempat sisa itu. Kode penerima tidak dipakai. Pada halaman 1 cetakan sungguhan terpilih 9 mm (salinan A) dan 6 mm (salinan B; 9 mm pada foto yang diperkecil), dan medannya menjelaskan 34 sampai 36 % pada putaran pertama (tanda masih ikut terhitung) dan 70 sampai 79 % sesudahnya.

| Halaman 1 | Bit kata salah, foto asli | Setelah aplikasi pesan | Kanal geser saja, foto asli (skor / ambang) | Setelah aplikasi pesan |
|---|---|---|---|---|
| Salinan A | 25 % menjadi 16 % | 41 % menjadi 20 % | 0,96 sampai 0,97 menjadi 1,17 sampai 1,18: disebut 3 dari 3 | 0,30 sampai 0,42 menjadi 0,91 sampai 0,95 |
| Salinan B | 26 % menjadi 22 % | 42 % menjadi 30 % | 0,76 sampai 0,80 menjadi 0,87 sampai 0,88 | 0,19 sampai 0,25 menjadi 0,58 sampai 0,61 |

* **Tidak ada yang mundur.** Ke-36 pelacakan tetap benar, skor orang lain paling tinggi 0,51 kali ambang (kanal geser saja 0,30), dan terhadap penerbitan lain 0 dari 18. Ke-13 foto lembar tanpa tanda, dilacak ulang terhadap penerbitan salinan A, tetap tidak menuduh siapa pun (paling tinggi 0,35 kali ambang). Skema v1 (salinan C) tidak berubah sama sekali: kelompok datanya sudah dibaca terhadap dua tetangga kontrol.
* **Bukti tanpa geseran lokal tidak tersentuh.** Pada foto simulasi cetakan salinan yang sama (lembar datar) dan pada foto cetak benchmark README medan itu menjelaskan 0 sampai 18 %, di bawah seperempat, jadi tidak ada kernel yang terpilih dan pengamatannya sama persis dengan dekoder sebelumnya: `make bench-check` mengulang ke-128 pelacakan benchmark dari awal dan hasilnya sama byte demi byte. Begitu juga salinan PDF yang persis dan halaman pindaian.
* **Yang tidak membantu.** Meluruskan gambar dengan medan registrasi yang lebih halus (10 mm pada arah baris) di atas medan lokal: salinan A turun dari 1,18 menjadi 1,14, salinan B naik dari 0,87 menjadi 0,90. Medan halus itu ikut menelan tanda (14 % pada 7 mm), jadi tidak dipakai.
* **Salinan B tetap lebih sulit.** Amplitudo tanda yang terukur di sana 0,61 kali besar terbitnya (salinan A 0,70). Mungkin raster abu-abu profil latar cetak mengganggu pencocokan kata; belum diperiksa.

Batasnya: medan lokal ditemukan dan diukur pada foto yang sama (dua lembar, satu printer, satu halaman), jadi angka di atas bukan uji tertahan. Pemilihan kernelnya buta kode, tetapi keputusan memakai medan itu lahir dari data ini.

Sesudah medan lokal, sisa kedua lembar masih berkorelasi 0,49 (0,06 pt per lembar, separuhnya bersama). Foto dokumen induk yang dicetak dengan printer yang sama ("lembar acuan") dapat mengukur bagian bersama itu, tetapi satu lembar acuan membawa derau lembarnya sendiri sebesar yang dibuangnya, jadi tidak menolong; baru rata-rata beberapa lembar acuan memberi sedikit (perkiraan dari angka ini: derau turun dari 0,06 menjadi 0,05 pt dengan empat lembar). Tidak dibuat.

## Foto yang lebih buruk

Ke-18 foto di atas tajam, tegak lurus, dan memuat seluruh halaman. `tekan.py` memperburuk setiap foto dengan satu hal sekaligus dan melacaknya lagi dengan semua kanal (`hasil/tekan.jsonl`, protokol `hasil/protokol_tekan.json` ditetapkan sebelum dijalankan). Cetakan dan kameranya sungguhan; perlakuan sesudahnya simulasi.

| Perlakuan | Halaman 1 (penuh teks), 9 foto | Halaman 2 (pendek), 9 foto |
|---|---|---|
| Diteruskan lebih kecil: sisi panjang 1280, 1024, 800 px | 27 dari 27 | 27 dari 27 |
| Sisi panjang 640 px (halaman pada sekitar 52 dpi) | 9 dari 9 | 7 dari 9 (2 tidak ditemukan) |
| Dipotong: paruh atas bingkai | 9 dari 9 | 9 dari 9 |
| Dipotong: paruh bawah bingkai | 9 dari 9 | 1 dari 9 |
| Dipotong: bagian tengah (seperempat bingkai) | 9 dari 9 (skor 1,8 sampai 3,7) | 0 dari 9 |
| Dilihat 30 derajat dari tegak lurus | 9 dari 9 | 9 dari 9 |
| Buram (Gauss 1,5 px pada 1600 px) | 9 dari 9 | 9 dari 9 |
| Terlalu terang (kertas 10 % di atas putih, terpotong) | 9 dari 9 | 9 dari 9 |

* **Halaman penuh teks: 90 dari 90**, pada ketiga salinan, juga dari seperempat bingkai dan pada 52 dpi. Seluruhnya 152 dari 180.
* **Tidak ada tuduhan salah** dalam 180 pelacakan; skor orang lain paling tinggi 0,53 kali ambang.
* **Yang gagal adalah potongan yang hampir kosong.** Paruh bawah dan bagian tengah halaman 2 hanya memuat kertas kosong dan dua baris kaki halaman, jadi tidak ada teks untuk registrasi. Pada 5 dari 9 potongan paruh bawah registrasi menerima pose yang salah (korelasi 0,76 sampai 0,88 pada skala yang keliru); bit yang lalu terbaca acak (43 sampai 46 % salah) dan tidak ada yang tertuduh. Potongan seperti itu tidak membocorkan isi, tetapi pose salah pada potongan yang nyaris tanpa teks belum ditolak.

Batasnya: perlakuannya simulasi di atas foto yang tajam; lembar bertanda yang sungguh kusut, basah, atau difoto miring belum ada.

## Bentuk lembar sungguhan pada salinan yang diketahui

Lembar yang difoto tidak bertanda, jadi tidak dapat menjawab apakah sebuah tanda terbaca. Tetapi setiap foto memberi bentuk lembarnya di bawah kamera: medan halus registrasi (`hasil/medan.json`, tanpa tanda di dalamnya). `putar.py` menaruh bentuk itu pada salinan simulasi yang penerimanya diketahui: halaman dicetak printer laser simulasi, isinya digeser menurut medan itu, lalu difoto ponsel simulasi pada 4000 px (sekitar 250 dpi, seperti foto iPhone). Yang sungguhan hanya geometrinya (lengkung, gelombang, lipatan, lensa ponsel); printer, derau kamera, dan cahaya tetap simulasi. Tidak ada yang dipilih di sini: dekoder apa adanya, protokol ditetapkan sebelum dijalankan (`hasil/protokol_putar.json`).

Catatan sesudah cetakan sungguhan: printer simulasi di bagian ini membuang pola profil bawaan (asumsi ambang sorotan), sedangkan printer sungguhan yang diuji mencetaknya. Angka "skema v2, latar bawaan: 0 dari 16" di bawah karena itu berlaku untuk printer yang tidak mencetak pola bawaan; yang tetap berlaku umum adalah kesimpulan tentang kanal geser dan tentang profil cetak.

Tiga penerbitan dari salinan yang sama, yaitu tiga jenis yang dicetak tim: skema v2 bawaan, skema v2 dengan profil latar cetak, dan skema v1. Dua dokumen contoh (halaman 1), dua salinan, lembar datar dan empat bentuk lembar sungguhan (dua foto lembar datar yang difoto miring, satu lembar basah, satu lembar kusut): 60 foto.

| Penerbitan | Lembar datar (simulasi biasa) | Bentuk lembar sungguhan | Bit salah pada bentuk sungguhan |
|---|---|---|---|
| skema v2, latar bawaan | disebut 4 dari 4 (skor 1,2 sampai 1,4 kali ambang) | disebut **0 dari 16** (skor paling tinggi 0,48 kali ambang) | kata 43 % (37 sampai 49 % per lembar; datar 2,9 %), baris 23 % (datar 0 %) |
| skema v2, profil latar cetak | disebut 4 dari 4 (2,4 sampai 4,6 kali) | disebut **16 dari 16** (1,5 sampai 4,6 kali) | latar 8,7 % (5 sampai 14 % per lembar; datar 6,7 %) dari sekitar 1.860 bit per foto |
| skema v1, latar bawaan | disebut 0 dari 4 (semua bit benar, tetapi hanya 97 posisi: 0,67 sampai 0,81 kali ambang) | disebut 0 dari 16 (paling tinggi 0,52 kali) | kata 32 %, baris 22 % |

* **Tanda geser tidak bertahan pada kertas sungguhan.** Dengan bentuk lembar sungguhan bit kata skema v2 hampir sama dengan menebak (43 % salah), juga pada lembar yang hanya datar di meja, dan bit baris 23 % salah. Angka cetak kami selama ini (satu halaman v2 disebut pada semua foto 4000 px) berlaku untuk lembar yang datar sempurna saja.
* **Pola latar profil cetak bertahan**, juga pada lembar kusut: pola dua dimensi itu dibaca per petak dan tidak peka terhadap geseran sepersekian milimeter. Yang belum diketahui: apakah printer sungguhan mencetak pola abu-abu muda itu (simulator mengasumsikan ya).
* **Tidak ada tuduhan salah** dalam 60 pelacakan (skor orang lain paling tinggi 0,34 kali ambang), dan ke-60 halaman ditemukan (48 lewat langkah halaman tidak datar).

**Putaran kedua** (`putar.py jalan --putaran 2`, protokol `hasil/protokol_putar2.json` ditetapkan setelah hasil di atas dan sebelum dijalankan; 100 foto baru, dokumen, salinan, dan bentuk lembar yang sama) menjawab dua pertanyaan yang tersisa:

| Pertanyaan | Lembar datar | Bentuk lembar sungguhan |
|---|---|---|
| Profil latar cetak pada foto 1600 px (ukuran kiriman aplikasi pesan, sekitar 100 dpi) | disebut 4 dari 4 | disebut **16 dari 16** (skor 4,3 sampai 4,7 kali ambang; bit latar 1,2 % salah) |
| Profil latar cetak pada foto 2400 px (sekitar 150 dpi) | disebut 4 dari 4 | disebut **16 dari 16** (1,1 sampai 4,7 kali; bit latar 5,8 % salah) |
| Geser kata v2 diperbesar menjadi 0,05 mm, foto 4000 px | disebut 4 dari 4 | disebut 0 dari 16 (bit kata 34 % salah) |
| Geser kata v2 0,10 mm | disebut 4 dari 4 | disebut 1 dari 16 (24 % salah) |
| Geser kata v2 0,15 mm, enam kali bawaan | disebut 4 dari 4 | disebut 3 dari 16 (18 % salah) |

* **Profil cetak tidak bergantung pada foto tajam.** Juga foto sekecil kiriman aplikasi pesan menyebut salinan yang benar pada setiap bentuk lembar.
* **Memperbesar geser kata bukan jalan keluar.** Geser 0,15 mm sudah mengubah celah kata sampai 0,3 mm, dan tetap hanya 3 dari 16. Geser di atas batas penerbitan (0,025 mm) hanya ada di studi ini: batas `pdf_shift` dilonggarkan di dalam skrip, tidak ada yang diterbitkan begitu.
* Tidak ada tuduhan salah dalam 100 pelacakan itu (skor orang lain paling tinggi 0,36 kali ambang), dan semua halaman ditemukan.

Batasnya: 4 bentuk lembar dari satu sesi foto, satu printer simulasi, dua dokumen pendek, dua salinan. Medan halus juga sudah dihaluskan (blok 6,5 mm), jadi gerak kertas yang lebih halus dari itu tidak ikut diputar ulang; cetakan sungguhan dapat lebih buruk bagi tanda geser, tidak lebih baik.

## Distorsi lensa pada foto layar

Simulator foto punya lensa yang mengaburkan tetapi sempurna secara geometri: garis lurus tetap lurus. Lensa ponsel membengkokkannya, juga setelah koreksi ponsel sendiri (beberapa persepuluh persen sampai sekitar satu persen di sudut bingkai). Foto sungguhan di atas memuat distorsi itu bersama bentuk kertas. `lensa.py` memisahkannya: foto salinan di layar (profil latar bawaan, seperti benchmark README) diberi distorsi radial 0, 0,3 %, dan 1 % (bantal dan tong) lalu dilacak apa adanya; 32 foto, 1600 px dan 4000 px, protokol ditetapkan sebelum dijalankan (`hasil/protokol_lensa.json`).

Semua 32 foto menyebut salinan yang benar (skor 2,0 sampai 4,7 kali ambang), dengan dan tanpa distorsi. Bit latar 1,5 sampai 3,3 % salah dan bit kata 3 sampai 11 % (tanpa distorsi 1,6 % dan 3 sampai 6 %); hanya satu foto yang memerlukan langkah halaman tidak datar. Distorsi lensa saja karena itu bukan yang menggagalkan foto sungguhan; bentuk kertaslah penyebabnya, dan skenario utama (foto layar) tidak terganggu olehnya dalam simulasi. Foto layar sungguhan sudah diminta dari tim.

## Lembar kalibrasi printer

Yang tidak dapat dijawab `putar.py`: apakah printer sungguhan mencetak pola abu-abu muda itu. Printernya di sana simulasi, dan ambang sorotannya (tingkat di atas sekitar 250 tercetak sebagai kertas polos) tidak pernah diukur. `kalibrasi.py buat` membuat satu lembar A4 untuk mengukurnya: 18 petak pola yang sama jenisnya (sel 2 mm, tanda per sel, digambar seperti `pattern_image`), dari dasar 253 (profil bawaan) sampai 238, dengan amplitudo 2, 3, dan 5. Lembar itu tidak memuat isi dokumen. `kalibrasi.py ukur` meregistrasi foto lembar yang dicetak dan melaporkan per petak: seberapa gelap tercetak, korelasi sel yang difoto dengan tandanya, dan bagian bit salah yang akan dimiliki satu posisi kode dari delapan sel.

Pemeriksaan alatnya sendiri (tanpa printer sungguhan): pada render bersih ke-18 petak terbaca dengan korelasi 0,97 sampai 0,99. Pada cetakan laser simulasi dengan bentuk lembar sungguhan, difoto ponsel simulasi 4000 px, petak profil bawaan (253 +/- 2) hilang (korelasi -0,07), seperti yang diasumsikan simulator, dan setiap petak dari 251 +/- 3 ke bawah terbaca (korelasi 0,57 sampai 0,94). Lembar ini sudah diserahkan ke tim bersama tiga salinan uji; fotonya belum ada. Cetakan salinan A dan C sudah menunjukkan bahwa printer tim mencetak pola 253 +/- 2.

## Yang berikutnya

1. Printer lain, terutama laser kantor dan mode hemat toner: profil bawaan di kertas bergantung pada printer, dan baru satu yang diuji. Lembar kalibrasi mengukurnya dengan satu cetakan.
2. Cetakan salinan bertanda yang tidak rata (kusut, basah, sobek) dan difoto miring; simulasi dengan bentuk lembar sungguhan memperkirakan profil cetak bertahan.
3. Foto layar sungguhan (skenario utama demo); sudah diminta dari tim.
4. Uji tertahan untuk [medan lokal](#medan-lokal-kelompok-kata): cetakan baru (salinan lain, dokumen lain, printer lain) yang tidak ikut menentukannya. Pada bentuk lembar kusut dan basah yang diputar ulang di simulasi, percobaan awal medan seperti itu hanya membawa 35 % bit kata salah menjadi 31 %.

## Mengulang

```bash
tapak --data DATA --keys KEYS keys init
tapak --data DATA --keys KEYS issue samples/surat_telegram.pdf samples/recipients.csv --canary-domain ""
PYTHONPATH=. python research/fotoasli/ukur.py foto FOLDER_FOTO --induk samples/surat_telegram.pdf \
    --lain samples/nota_dinas.pdf --data DATA --keys KEYS --doc HASH
PYTHONPATH=. python research/fotoasli/ukur.py geser
PYTHONPATH=. python research/fotoasli/putar.py jalan     # 60 foto, sekitar 45 menit dengan 3 proses
PYTHONPATH=. python research/fotoasli/putar.py ringkas
PYTHONPATH=. python research/fotoasli/salinan.py FOLDER_FOTO --isu A=DIR_A:7,B=DIR_B:13,C=DIR_C:4 --kunci code_secret.key
PYTHONPATH=. python research/fotoasli/salinan.py --ringkas   # --hasil BERKAS untuk berkas hasil lain
PYTHONPATH=. python research/fotoasli/tekan.py jalan FOLDER_FOTO --isu A=DIR_A:7,B=DIR_B:13,C=DIR_C:4 --kunci code_secret.key
PYTHONPATH=. python research/fotoasli/tekan.py ringkas
PYTHONPATH=. python research/fotoasli/kalibrasi.py buat lembar_K.pdf
PYTHONPATH=. python research/fotoasli/kalibrasi.py ukur lembar_K.pdf FOTO_LEMBAR_K.jpg
```

Angka lacak (skor dan ambang) bergantung pada penerbitan yang dibuat untuk studi; registrasi dan geseran tidak.
