# Keamanan, registri, dan batasan

[Kembali ke README](../README.md) · [Cara kerja](cara-kerja.md) · [Operasi](operasi.md)

## Minimisasi data

* Registri hanya berisi:
  * hash dokumen dan hash nama berkas (bukan namanya);
  * parameter kode, id penerima, id salinan, dan komitmen kode;
  * nama kanal, id varian, waktu, dan penerbit;
  * hash berkas salinan dan digest token kanari;
  * komitmen berkunci identitas penerima;
  * untuk setiap pelacakan: nomor urut, hash berkas bukti, dan jatah eps, tanpa nama dan tanpa putusan. Bila buktinya berkas salinan yang persis sama, hash bukti sama dengan `file_sha256` salinan itu, sehingga pembaca registri dapat melihat salinan mana yang diserahkan sebagai bukti.

  Registri tidak menyimpan teks dokumen, gambar, maupun nama penerima.
* Nama penerima hanya ada di catatan penerbitan lokal (`manifest.json`).
* Teks varian semantik adalah isi dokumen. Teks itu disimpan di folder dokumen (`varian.json`) bersama PDF induk; registri hanya menyimpan hash-nya.
* Titik pilihan kata (bentuk dan baris konteksnya) juga isi dokumen. Berkas tinjauannya disimpan di folder dokumen (`leksikal.json`), bukan di registri atau log. Registri hanya menyimpan digest berkas itu, versi dan digest leksikon, aturan posisi, serta nomor baris dan kata titiknya. Entri salinan tidak menyimpan bentuk yang dipilih untuk salinan itu, karena pilihan itu adalah bit kode; pilihan dihitung ulang dari rahasia kode saat pelacakan. Pemindaian dan peninjauan melaporkan penolakan hanya per kategori.
* `semantic_variant_ids` (misalnya `u0:v2`) dicatat di registri sesuai spesifikasi. Akibatnya, pembaca registri dapat melihat salinan mana yang menerima varian sama. Ini setara dengan beberapa bit kode (4 dari sekitar 3000 posisi pada contoh). Registri dipegang oleh satuan penerbit dan eselon atas, bukan oleh penerima. Bila kebocoran ini dianggap terlalu besar, kolom itu dapat dikosongkan karena id varian dapat dihitung ulang dari rahasia kode saat pelacakan.

## Kapan nama boleh disebut

Sebelum dekode dan sebelum menyebut nama, pelacakan memeriksa tiga hal:
1. rantai registri terverifikasi;
2. parameter kode dokumen (c, eps, N, konstanta, kanal, ambang penuh) cocok dengan entri dokumen;
3. setiap salinan cocok dengan registri, tepat satu entri per salinan. Yang dicocokkan adalah id penerima, nomor, komitmen kode, hash berkas, dan komitmen nama, jabatan, serta satuan.

Pelacakan berhenti tanpa menyebut nama bila:
* kunci publik ada tetapi dokumen tidak ditemukan di registri, misalnya berkas hilang atau terpotong, atau dokumen diterbitkan dengan `--no-registry` di instalasi yang memiliki kunci;
* rantai gagal diverifikasi;
* salah satu pencocokan di atas gagal;
* pelacakan tidak dapat dicatat di registri (lihat [batasan 13](#batasan)). Pencatatan dilakukan setelah ketiga pemeriksaan lulus dan sebelum bukti dibaca.

Tanpa kunci publik, rantai tidak diverifikasi; pelacakan tetap berjalan dan hasilnya menyebut hal itu.

Mode lepas `tapak trace ... --master --manifest` (perintah ulang di berita acara) tidak memeriksa registri. Mode ini menyatakannya di keluaran dan tidak membuat berita acara. Entri yang belum bertanda tangan tidak menghentikan pelacakan, tetapi ditandai jelas di hasil, CLI, dan berita acara karena belum terlindungi dari pemalsuan.

## Kunci dan kode

* Kode setiap penerima diturunkan dari rahasia kode dengan SHAKE-256. Kode dapat dibangkitkan ulang bit demi bit bertahun-tahun kemudian dan tidak bergantung versi numpy. Sebelum pelacakan, kode diperiksa terhadap komitmennya.
* Kunci tanda tangan registri tidak pernah dibuat diam-diam; hanya `tapak keys init` yang membuatnya. Tanpa kunci, entri dicatat tanpa tanda tangan, laporan menandainya dengan jelas, dan pemegang kunci menandatanganinya kemudian.
* Tabel registri dijaga trigger tambah-saja. Perubahan yang melewati trigger tetap terdeteksi karena rantai hash dan tanda tangan.

## Kanari DNS

Pendengar DNS kanari adalah satu-satunya bagian yang menghadap internet.
* Pendengar memakai basis data sendiri di `data/kanari/`.
* Pendengar hanya mencatat token yang benar-benar diterbitkan (daftar digest di `data/kanari-izin/`), sehingga nama karangan tidak dapat membengkakkan log.
* Daftar itu disusun ulang dari catatan penerbitan, ditulis dengan nama sementara acak, lalu diganti namanya. Aplikasi tidak pernah membaca atau mengikuti tautan di folder yang dapat ditulis pendengar.
* Aplikasi membaca `kanari.db` lewat satu deskriptor, tanpa mengikuti tautan dan tanpa memblokir, hanya untuk berkas biasa dengan ukuran terbatas. Tautan atau FIFO yang ditanam tidak dapat dipakai untuk membaca rahasia atau membuat aplikasi macet.
* Di Docker, kontainer pendengar hanya melihat kedua folder itu (folder daftar izin hanya-baca). Kontainer berjalan sebagai pengguna non-root di port 5353, di jaringan terpisah dari aplikasi web.

## Aplikasi web dan masukan

* Aplikasi web tidak memiliki login. Jalankan hanya di 127.0.0.1 (bawaan) atau di belakang proksi yang mengautentikasi.
* Aplikasi menolak header Host asing, sebagai perlindungan dari DNS rebinding. Aplikasi juga menolak permintaan POST dari asal lain, termasuk aplikasi lain di port localhost yang berbeda.
* Berkas data dibuat dengan izin hanya-pemilik (umask 077).
* TAPAK menolak gambar bukti di atas 60 megapiksel hanya dengan membaca kepala berkasnya. PNG dan JPEG diperiksa TAPAK; format lain dibatasi oleh `OPENCV_IO_MAX_IMAGE_PIXELS`.
* Halaman PDF yang dibaca sebagai gambar dibatasi per pelacakan:
  * paling banyak dua kali jumlah halaman induk, minimal 4;
  * 60 megapiksel total;
  * berhenti setelah dua halaman berturut-turut yang tidak cocok.
* Hasil render bukti tidak disimpan di memori setelah permintaan, dan antarmuka web menjalankan paling banyak dua pelacakan sekaligus.
* Satu-satunya lalu lintas jaringan dari luar adalah kueri DNS yang diterima pendengar kanari. Antarmuka web memuat HTMX dan font dari server lokal.

## Format registri (untuk auditor)

* **Entri.** `entry_hash = SHA-256(JSON kanonis {seq, kind, payload, prev_hash, created_at})`. JSON kanonis berarti kunci terurut, tanpa spasi, UTF-8. `prev_hash` entri pertama adalah 64 angka nol. Tanda tangan Ed25519 dibuat atas 32 byte `entry_hash`.
* **Jenis `document`.** Memuat parameter kode, kanal, ringkasan rencana, serta aturan dan nilai ambang. Dokumen yang memakai kanal pilihan kata juga memuat `retype_positions`, `lexical_digest`, `lexicon_version`, `lexicon_digest`, `shift_excluded_rows`, dan `text_excluded_words`: aturan posisi, digest, dan nomor posisi, tanpa kata. Keenamnya selalu hadir bersama dan diperiksa `tapak verify`. Dokumen tanpa kanal itu memiliki entri yang sama persis dengan sebelumnya.
* **Jenis `copy`.** Memuat `doc_hash`, `recipient_id`, `copy_id`, `seq`, `code_digest`, `channels_used`, `semantic_variant_ids`, `issued_at`, `issuer`, dan `file_sha256`.
  * `canary_token` disimpan sebagai hash `sha256:`, bukan token aslinya.
  * `recipient_mac` adalah HMAC-SHA256 dengan rahasia kode atas id, nama, jabatan, dan satuan penerima. Nama jadi terikat ke entri bertanda tangan tanpa tersimpan di registri, dan tidak dapat ditebak dari daftar personel.
* **Jenis `trace`.** Satu entri per pelacakan dokumen yang tercatat, ditulis sebelum bukti dibaca. Memuat `doc_hash`, `trace_no` (1, 2, 3, ... per dokumen), `evidence_sha256` (daftar hash berkas bukti), `eps` (target dokumen), `eps_share` (= eps x 6 / (pi^2 k^2) untuk pelacakan ke-k), dan `created_at` (sama dengan waktu entri). Tidak ada nama, putusan, atau isi dokumen. Selain rantai dan tanda tangan, verifikator memeriksa bahwa nomor pelacakan per dokumen berurutan tanpa ganda atau lompatan, `eps_share` sesuai jadwal, dan `eps` sama dengan entri dokumennya. Registri lama tanpa entri `trace` tetap lulus verifikasi. Berita acara dan keluaran CLI mencetak nomor dan hash entri ini sebagai jangkar untuk `tapak verify --jangkar`.
* **Akar Merkle harian.**
  * Daun adalah 32 byte mentah `entry_hash`. Simpul adalah SHA-256(kiri || kanan); simpul ganjil digandakan, dan satu daun adalah akarnya sendiri.
  * Berkas `merkle-YYYY-MM-DD.txt` hanya dibuat untuk hari UTC yang sudah selesai; hari berjalan ditulis sebagai `.partial.txt` (sementara).
  * Setiap berkas memuat hash berkas hari sebelumnya. Penghapusan entri di ujung rantai pun terdeteksi bila berkas akar disimpan di luar sistem.
* **Kunci.** Berkas kunci tanda tangan berisi `ed25519-seed:<64 hex>`; kunci publik berupa 64 hex.
* **Log kanari.** Peristiwa kanari dicatat di berkas terpisah `data/kanari/kanari.db` (tabel `canary_events` dengan rantai hash sendiri), bukan di registri. `python -m tapak.canary_dns --anchor` menambatkan ujungnya ke registri bertanda tangan.

## Batasan

1. **Teks yang diketik ulang hanya membawa sedikit bit.** Pengetikan ulang menghapus kanal geser, latar, dan teks. Yang tersisa hanya varian semantik dan, bila penerbit memilihnya, pilihan kata ([cara kerja](cara-kerja.md#kanal-pilihan-kata-opsional)).
   * **Dokumen pendek tetap "tidak cukup bukti".** Contoh nota dinas 2 halaman membawa 4 bit semantik dan 11 bit pilihan kata; surat telegram membawa 5 bit pilihan kata. Pilihan kata memberi sekitar 3,6 bit per 100 kata isi, atau sekitar 10 bit per halaman isi penuh. Terukur (simulasi pengetikan ulang, pelacakan pertama yang tercatat, N = 20): pada 883 kata isi (31 bit) hanya 12 dari 200 percobaan yang menyebut pembocornya; pada 1.318 kata isi (47 bit), 200 dari 200. Jadi satu pembocor tunggal mulai dapat disebut dari sekitar 1.300 kata isi (4 sampai 5 halaman isi). TAPAK sendiri baru menyatakan "cukup untuk satu pembocor" mulai 64 bit, sekitar 1.800 kata isi (6 halaman isi penuh), sebagai cadangan untuk derau berat dan kebiasaan pengetik. Di bawah itu, berita acara menyebut jumlah bit yang terbaca dan alasan "tidak cukup bukti". Penerbit melihat jumlah bit dan kekurangannya sebelum menerbitkan.
   * **Tidak tahan kolusi.** Posisi kanal ini diambil dari pita bias 0,3 sampai 0,7 agar satu pembocor cepat tertangkap. Akibatnya koalisi yang memilih bentuk minoritas menekan skornya ke sekitar nol. Ketahanan kolusi dari teks ketikan ulang di luar jangkauan: dengan posisi seragam pun perlu sekitar 1.000 sampai 1.500 bit, kira-kira 90 sampai 140 halaman isi.
   * **Dapat dihapus.** Pembocor yang tahu kanal ini dapat menulis ulang kata penghubung dan kata depan, sama seperti menulis ulang kalimat pembuka dan penutup. Bukti itu hilang. Mengganti kata secara acak tidak memfitnah siapa pun, karena bentuk acak tidak cocok dengan salinan mana pun.
   * **Dapat ditiru untuk memfitnah.** Pilihan kata terlihat di kertas. Pembocor yang pernah membaca salinan orang lain (di meja, saat rapat, atau dari foto buram) dapat mengetik ulang bocorannya dengan pilihan kata salinan itu. Teks itu lalu sama dengan salinan orang lain yang diketik ulang, dan salinan itulah yang disebut, dengan batas tuduhan salah yang sangat kecil. Batas itu mengandaikan bentuk salinan tak bersalah tidak diketahui pembocor, dan syarat itu gugur begitu salinannya pernah dibaca orang lain. Karena itu, nama yang hanya didukung pilihan kata dan varian kalimat selalu diberi peringatan di bawah putusan (CLI, web, berita acara): hasil itu menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan memerlukan bukti pendukung. Lihat juga [batasan 13](#batasan).
   * **Salinan berbeda kata.** Penerima yang membandingkan salinannya akan melihat perbedaan pilihan kata. Satuan penerbit harus menerima bahwa teks naskah dinas berbeda per penerima, dengan makna yang sama dan dokumen induk sebagai catatan resmi. Ini keputusan kebijakan satuan penerbit, bukan keputusan teknis.
   * **Urutan kalimat dan teks berulang.** Bila dokumen induk mengulang frasa dengan konteks yang sama dan pembocor menukar urutan kalimat, titik itu dapat terbaca di tempat lain dengan yakin. Skor pembocor turun, tetapi salinan lain tidak tertuduh karenanya. Pemindaian menandai titik berkonteks berulang agar peninjau dapat menolaknya. Dokumen sintetis panjang yang dipakai untuk angka di atas mengulang paragrafnya, jadi angkanya berlaku untuk bocoran yang tidak menukar urutan kalimat.
   * **Tabel leksikon masih draf.** `naskah_dinas_v1.json` belum disahkan peninjau bahasa Tata Naskah Dinas, jadi setiap titik tetap ditinjau manusia. Pemeriksaan otomatis hanya menyaring, tidak menggantikan peninjauan. Keputusan setuju atau tolak di `leksikal.json` tidak diautentikasi: TAPAK menolak titik dan bentuk yang disunting di luar TAPAK, tetapi tidak dapat membedakan status yang disunting tangan. Berkas itu dijaga seperti dokumen induk.
   * **Kanal geser berkurang.** Baris yang memuat titik dikeluarkan dari kanal geser. Pada contoh nota dinas, kanal geser turun dari 183 menjadi 140 bit (23 %), sehingga atribusi foto salinan cetak, yang sudah tipis, makin tipis.
   * **Angkanya sintetis.** Pengetikan ulang dan OCR disimulasikan (`tapak/ketik.py`); belum ada orang sungguhan yang mengetik ulang. Pengetik yang terbiasa menulis bentuk induk pada 5 % titik menaikkan bit salah menjadi sekitar 3 %.
2. **Kapasitas kanal semantik kecil, dan dengan model lokal kecil hampir nol.** Kalimat yang memuat angka, nama, waktu, koordinat, atau perintah tidak dipakai. Dengan tabel frasa deterministik (`tapak/llm/mock.py`, dipakai di demo dan pengujian), setiap kalimat aman membawa 2 bit. Jalur llama.cpp sudah diuji dengan Qwen2.5-3B-Instruct dan Gemma 3 4B (GGUF Q4_K_M, CPU 4 utas) pada dua dokumen contoh:
   * **Hasil.** Dengan templat perintah sekarang, 24 pembangkitan (2 model, 2 dokumen, 2 kalimat, 3 kali) menghasilkan 19 varian yang lolos pemeriksaan otomatis dan pemeriksa model. Peninjau manusia hanya menyetujui 5, semuanya dari surat telegram. Hasilnya 4 bit dari 24 pembangkitan (rata-rata 0,17 bit per kalimat per pembangkitan), dan 0 bit untuk nota dinas. Empat pembangkitan baru lewat `tapak semantic suggest` dengan Gemma tidak menghasilkan varian yang layak disetujui.
   * **Pemeriksa model tidak dapat diandalkan.** Pada 24 pasangan uji yang ditetapkan sebelum pengujian, pemeriksa menerima 2 sampai 3 dari 12 pasangan yang maknanya berubah (misalnya "kami" menjadi "mereka"). Pada keluaran sungguhan, dari 33 kandidat yang diloloskan pemeriksa, manusia menyetujui 5. Keputusan manusia per varian adalah pengaman yang sesungguhnya, jadi TAPAK menolak persetujuan sekaligus untuk varian dari model, baik di web maupun di `tapak semantic approve --all`. Menolak semuanya sekaligus tetap boleh.
   * **Model menyisipkan kata perintah.** Sebanyak 70 dari 178 kandidat menambahkan kata seperti "wajib", "harus", "perlu", atau "segera". Pemeriksaan token terlindungi dan pemeriksaan keamanan menolak ke-70 kandidat itu.
   * **Lambat di CPU.** Satu pembangkitan untuk dua kalimat memerlukan 1,4 sampai 10 menit di CPU yang dipakai bersama (median 24 sampai 30 detik per panggilan parafrase dan 9 sampai 14 detik per panggilan pemeriksa).
   * **Belum diuji.** Model 7 sampai 8B (RAM mesin uji tidak cukup), jalur llama-cpp-python di dalam proses, dan Docker.
   * **Posisi pita bias.** Dokumen yang memakai kanal pilihan kata juga mengambil posisi semantiknya dari pita bias 0,3 sampai 0,7, jadi batasan kolusi pada butir 1 berlaku juga untuk bit semantiknya.
3. **Pola latar bawaan tidak bertahan saat dicetak.** Model printer kami mengasumsikan tingkat abu-abu di atas sekitar 250 tercetak sebagai kertas polos (belum diukur pada printer sungguhan), jadi foto salinan yang dicetak hanya membawa kanal geser, sekitar 80 sampai 100 posisi kode terbaca per halaman. Hasil uji sintetis (printer laser disimulasikan, foto sintetis, N = 100, eps = 10^-6, salinan 1 sampai 20, halaman 1 dan 2, dekoder yang dirilis; rincian di [cara kerja](cara-kerja.md#salinan-yang-dicetak)):
   * **Satu halaman tidak menyebut siapa pun:** 0 dari 40 pada 1600 px dan 0 dari 40 pada 4000 px, semuanya "tidak cukup bukti". Salinan yang benar selalu berskor tertinggi, tetapi hanya mencapai median 59 % dan 62 % dari ambang. Pada 4000 px semua bit yang terbaca benar, jadi batasnya kapasitas: satu pembocor perlu sekitar 300 posisi terbaca. Pada benchmark README (N = 20, 4 salinan) satu halaman cukup pada 2 dari 16 foto, keduanya dari salinan yang sama.
   * **Dua halaman salinan yang sama**, digabung dalam satu pelacakan (`tapak trace foto_hal1.jpg foto_hal2.jpg --doc ...`, atau pilih beberapa berkas di halaman Lacak): 5 dari 20 pada 1600 px dan 8 dari 20 pada 4000 px.
   * **Tidak ada tuduhan salah** dalam 120 pelacakan itu (80 satu halaman dan 40 dua halaman).
   * Angka lama "dua halaman cukup pada 5 dari 6" berasal dari simulasi yang hanya membuang pola latar tanpa memodelkan printer, dan terlalu optimistis.

   Karena itu, dengan profil bawaan, foto salinan yang dicetak belum tahan kolusi pada c = 3: menyebut minimal satu dari tiga anggota memerlukan 1.200 posisi atau lebih per pelacakan. **Profil latar cetak** (`tapak issue ... --latar cetak`, opsional) menggambar pola 242 +/- 5, di bawah ambang yang diasumsikan itu. Profil ini dipilih dari tiga kandidat setelah melihat hasilnya pada cetakan dan foto simulasi tertentu, jadi angkanya diukur ulang dengan protokol yang sama pada cetakan, foto, dan koalisi baru: satu halaman menyebut salinan yang benar pada 40 dari 40 foto, baik pada 1600 px maupun 4000 px, dan satu lembar potongan tiga salinan menyebut minimal satu anggota pada 31 dari 32 halaman (ketiganya pada 23), tanpa orang tak bersalah. Harganya: seluruh halaman tampak abu-abu muda (dL* -3,4 pada laser simulasi, -4,5 di layar) dan teksturnya di ambang terlihat (S-CIELAB rata-rata 1,1, sedangkan pola bawaan 0,4). Profil ini belum diuji dengan printer, ponsel, maupun pengamat sungguhan, dan hasilnya paling bergantung pada asumsi simulator printer (batasan 10).
4. **Foto yang terlalu terang juga menghapus pola latar** (banyak piksel kertas jenuh 255).
   * **Pemeriksaan.** Dekoder membandingkan energi pola asli dengan umpan, yaitu sel yang sama dengan tanda acak independen. Ujinya berupa uji z berpasangan atas selisih energi per bit dengan ambang tetap z = 3, sehingga peluang foto tanpa pola dianggap berpola sekitar 10^-3, berapa pun jumlah bit yang terlihat. Bila pola tidak lebih kuat dari derau, kanal latar tidak melaporkan apa pun dan catatan hasil menyebutnya. Uji ini tidak memakai kode penerima, jadi jauh kurang peka daripada skor tuduhan, dan pola yang lemah tidak selalu terdeteksi. Bila kanal geser saja tidak cukup, jawabannya "tidak cukup bukti".
   * **Tiga foto layar di benchmark gagal di sini** (39 sampai 51 % piksel jenuh). Satu tanpa pola sama sekali (50 % bit benar, setara tebakan). Dua lagi berpola lemah (62 dan 63 % bit benar, z = 0,9, jauh di bawah ambang). Kami tidak menurunkan ambang setelah melihat hasil ini.
   * **Jaminan tuduhan salah tidak terpengaruh.** Bobot tidak pernah memakai kode penerima. Gerbang ini hanya mencegah derau mengencerkan bukti kanal geser.
5. **Geser baris rentan pada tangkapan layar beresolusi rendah**, karena penampil PDF membulatkan garis dasar ke piksel. Dekoder menaksir derau per jenis dan otomatis memberi bobot kecil; geser kata (horizontal) tetap terbaca.
6. **Kanal teks tidak aman terhadap lawan yang paham.** Simbol lebar-nol dan huruf Kiril dapat dibersihkan atau diubah. Lawan tidak dapat memakainya untuk memfitnah orang lain karena tidak tahu kode penerima lain, tetapi dapat menghapus bukti di kanal ini. Pencarian frasa lintas kata di penampil PDF dapat gagal pada salinan bertanda; pencarian satu kata tetap berfungsi.
7. **Kanari bergantung pada penampil.** Adobe Reader menghubungi alamat aksi pembuka, tetapi lebih dulu menampilkan peringatan izin kepada setiap pembuka, termasuk penerima sah, sehingga kanari mudah dikenali dan dibuang. Word mengambil gambar eksternal. Penampil peramban dan MuPDF tidak mengambil apa pun. Demo mensimulasikan pencarian DNS yang dilakukan penampil. Di dalam jaringan satuan, DNS internal harus menjawab zona kanari secara lokal agar penerima sah tidak memicu peringatan.
8. **Masukan PDF harus berlapis teks.** TAPAK menggambar ulang setiap glif. Gerbang visual menolak penerbitan bila gambar ulang tanpa tanda tidak identik dengan aslinya, misalnya karena font tidak dapat dipakai ulang. Induk DOCX juga diterima, tetapi salinannya hanya membawa karakter tak terlihat, huruf kembar Kiril, dan kanari.
9. **Koalisi melebihi c** tetap tidak menimbulkan tuduhan salah, tetapi tidak semua anggotanya tertangkap (sekitar 45 % pada 5 orang melawan kode c=3).
10. **Foto dan cetakan sintetis bukan foto ponsel dan printer sungguhan.** Simulator foto mencakup perspektif, pencahayaan, bayangan, blur, derau, penajaman, dan JPEG ganda, tetapi tidak meniru pemrosesan gambar di kamera ponsel (pengurangan derau agresif, HDR, moire layar). Simulator printer (`PrintParams`, preset laser 600 dpi dan inkjet) meniru ambang sorotan, raster, banding, toner, kemiringan kertas, dan dot gain dengan nilai dari literatur dan perkiraan, bukan dari printer yang diukur. Perilaku titik terkecil, koreksi nada driver, mode hemat toner, printer warna, dan mesin fotokopi tidak diketahui atau tidak dimodelkan. Benchmark README melaporkan foto layar dan foto kertas cetak secara terpisah; gambar alur dan tangkapan layar Lacak memakai foto layar. Kami belum menguji dengan ponsel atau printer sungguhan.
11. **Tanda air berbasis model (StegaStamp) belum dilatih.** Kerangkanya ada di `tapak/learned_wm/` (model, degradasi, pelatihan, ekspor ONNX) dan masih berisi TODO. Yang dipakai sekarang adalah dekoder korelasi.
12. **Konstanta 2 pi^2 dengan skor simetris belum terbukti untuk c kecil** (hanya asimtotik). Ini memengaruhi deteksi, bukan tuduhan salah; deteksi diukur dengan simulasi di [cara kerja](cara-kerja.md#angka-simulasi). Konstanta 100 tersedia sebagai pilihan konservatif.
13. **Batas tuduhan salah bersyarat.** Batas 10^-6 hanya berlaku bila rahasia kode tidak bocor dan catatan penerbitan tidak diubah. Untuk nama yang hanya didukung tanda yang terlihat di kertas (pilihan kata dan varian kalimat dari teks ketikan ulang) ada syarat ketiga: tidak ada orang lain yang pernah membaca salinan itu, karena pembacanya dapat meniru pilihan katanya ([butir 1](#batasan)). Hasil dan berita acara memberi peringatan untuk nama seperti itu. TAPAK menunjuk salinan dan penerima yang tercatat untuk salinan itu, bukan orang yang membocorkannya.
    * **Pelacakan berulang diperhitungkan.** Setiap pelacakan dokumen yang tercatat lebih dulu ditulis sebagai entri `trace`, sebelum bukti dibaca. Pelacakan ke-k hanya memakai jatah eps x 6 / (pi^2 k^2): sekitar 61 %, 15 %, dan 7 % dari eps untuk k = 1, 2, 3. Jumlah semua jatah tepat eps, jadi batas 10^-6 berlaku untuk semua pelacakan dokumen itu bersama, berapa pun banyaknya (syaratnya di bawah). Peluang tuduhan salah per salinan juga dibagi dengan 6 / (pi^2 k^2). Jadwalnya tetap dan nomor k diketahui sebelum dekode, jadi tidak ada yang disesuaikan setelah melihat hasil.
    * **Harganya kecil.** Untuk N = 20 dan c = 3 dengan pembacaan penuh, ambang Z naik dari 339 (seluruh eps) menjadi 345 pada pelacakan pertama, 359 pada pelacakan kedua, 392 pada pelacakan kesepuluh, dan 435 pada pelacakan keseratus. Pelacakan yang gagal setelah dicatat tetap memakai nomornya.
    * **Yang masih tersisa.**
      * Mode lepas `tapak trace --master --manifest` dan dokumen yang diterbitkan dengan `--no-registry` tanpa kunci publik tidak dicatat. Keduanya memakai seluruh eps dan hasilnya menyatakan bahwa pelacakan berulang tidak diperhitungkan; mode lepas juga tidak membuat berita acara. `--pelacakan-ke K` di mode lepas hanya mengulang pelacakan ke-K dengan jatahnya, sehingga ambangnya lebih tinggi daripada mode lepas biasa.
      * Bila kunci publik terpasang, menghapus registri tidak menolong (dokumen yang tidak ada di registri tidak dilacak dengan nama), dan mengubah entri bertanda tangan memutus tanda tangannya. Namun entri pelacakan terakhir yang dihapus dari ujung rantai, dengan menyunting berkas di luar TAPAK, tidak terlihat oleh pelacakan berikutnya: pelacakan itu mendapat nomor dan jatah yang sama lagi. Penghapusan ini hanya terungkap oleh `tapak verify --jangkar` dengan jangkar yang tercetak di berita acara pelacakan yang dihapus, atau oleh akar Merkle yang disimpan di luar sistem.
      * Jumlah jatah membatasi tuduhan salah bila bukti setiap pelacakan tidak dipilih berdasarkan skor pelacakan sebelumnya, misalnya membuang halaman bukti agar skor tertinggi naik. Bukti baru, rencana pelacakan yang ditetapkan lebih dulu, dan keputusan untuk melacak lagi atau berhenti tidak melanggar syarat ini.
      * Pelacakan pada salinan berkas registri di komputer lain hanya tercatat di salinan itu.
