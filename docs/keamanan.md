# Keamanan, registri, dan batasan

[Kembali ke README](../README.md) · [Cara kerja](cara-kerja.md) · [Operasi](operasi.md)

## Minimisasi data

* Registri hanya berisi:
  * hash dokumen dan hash nama berkas (bukan namanya);
  * parameter kode, id penerima, id salinan, dan komitmen kode;
  * nama kanal, id varian, waktu, dan penerbit;
  * hash berkas salinan dan digest token kanari;
  * komitmen berkunci identitas penerima.

  Registri tidak menyimpan teks dokumen, gambar, maupun nama penerima.
* Nama penerima hanya ada di catatan penerbitan lokal (`manifest.json`).
* Teks varian semantik adalah isi dokumen. Teks itu disimpan di folder dokumen (`varian.json`) bersama PDF induk; registri hanya menyimpan hash-nya.
* `semantic_variant_ids` (misalnya `u0:v2`) dicatat di registri sesuai spesifikasi. Akibatnya, pembaca registri dapat melihat salinan mana yang menerima varian sama. Ini setara dengan beberapa bit kode (4 dari sekitar 3000 posisi pada contoh). Registri dipegang oleh satuan penerbit dan eselon atas, bukan oleh penerima. Bila kebocoran ini dianggap terlalu besar, kolom itu dapat dikosongkan karena id varian dapat dihitung ulang dari rahasia kode saat pelacakan.

## Kapan nama boleh disebut

Sebelum dekode dan sebelum menyebut nama, pelacakan memeriksa tiga hal:
1. rantai registri terverifikasi;
2. parameter kode dokumen (c, eps, N, konstanta, kanal, ambang penuh) cocok dengan entri dokumen;
3. setiap salinan cocok dengan registri, tepat satu entri per salinan. Yang dicocokkan adalah id penerima, nomor, komitmen kode, hash berkas, dan komitmen nama, jabatan, serta satuan.

Pelacakan berhenti tanpa menyebut nama bila:
* kunci publik ada tetapi dokumen tidak ditemukan di registri, misalnya berkas hilang atau terpotong, atau dokumen diterbitkan dengan `--no-registry` di instalasi yang memiliki kunci;
* rantai gagal diverifikasi;
* salah satu pencocokan di atas gagal.

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
* **Jenis `document`.** Memuat parameter kode, kanal, ringkasan rencana, serta aturan dan nilai ambang.
* **Jenis `copy`.** Memuat `doc_hash`, `recipient_id`, `copy_id`, `seq`, `code_digest`, `channels_used`, `semantic_variant_ids`, `issued_at`, `issuer`, dan `file_sha256`.
  * `canary_token` disimpan sebagai hash `sha256:`, bukan token aslinya.
  * `recipient_mac` adalah HMAC-SHA256 dengan rahasia kode atas id, nama, jabatan, dan satuan penerima. Nama jadi terikat ke entri bertanda tangan tanpa tersimpan di registri, dan tidak dapat ditebak dari daftar personel.
* **Akar Merkle harian.**
  * Daun adalah 32 byte mentah `entry_hash`. Simpul adalah SHA-256(kiri || kanan); simpul ganjil digandakan, dan satu daun adalah akarnya sendiri.
  * Berkas `merkle-YYYY-MM-DD.txt` hanya dibuat untuk hari UTC yang sudah selesai; hari berjalan ditulis sebagai `.partial.txt` (sementara).
  * Setiap berkas memuat hash berkas hari sebelumnya. Penghapusan entri di ujung rantai pun terdeteksi bila berkas akar disimpan di luar sistem.
* **Kunci.** Berkas kunci tanda tangan berisi `ed25519-seed:<64 hex>`; kunci publik berupa 64 hex.
* **Log kanari.** Peristiwa kanari dicatat di berkas terpisah `data/kanari/kanari.db` (tabel `canary_events` dengan rantai hash sendiri), bukan di registri. `python -m tapak.canary_dns --anchor` menambatkan ujungnya ke registri bertanda tangan.

## Batasan

1. **Sidik hilang bila dokumen diketik ulang dan kalimat pembuka serta penutupnya ditulis ulang.** Kanal geser, latar, dan teks hilang, sedangkan kanal semantik hanya membawa sedikit bit (contoh nota dinas: 2 kalimat, 4 bit). Teks ketikan ulang yang mempertahankan kalimat itu tetap dapat dibaca bitnya, tetapi 4 bit tidak cukup untuk menuduh pada eps = 10^-6, sehingga keluarannya "tidak cukup bukti".
2. **Kapasitas kanal semantik kecil.** Sekitar 2 bit per kalimat aman yang disetujui. Kalimat yang memuat angka, nama, waktu, koordinat, atau perintah tidak dipakai. Varian di demo dan pengujian berasal dari tabel frasa deterministik (`tapak/llm/mock.py`); jalur llama.cpp lokal belum diuji dengan model sungguhan.
3. **Kanal latar tidak bertahan saat dicetak.** Printer menggambar tingkat abu-abu di atas sekitar 250 sebagai kertas polos, jadi foto dari salinan yang dicetak hanya membawa kanal geser (sekitar 80 sampai 100 bit per halaman). Hasil uji sintetis (cetak disimulasikan dengan membuang pola latar, foto sintetis 3000 px), eps = 10^-6, 6 salinan:
   * satu halaman tidak cukup: 0 dari 6, semuanya "tidak cukup bukti", walau salinan yang benar selalu berskor tertinggi;
   * dua halaman salinan yang sama, digabung dalam satu pelacakan (`tapak trace foto_hal1.jpg foto_hal2.jpg --doc ...`, atau pilih beberapa berkas di halaman Lacak), cukup untuk 5 dari 6 tanpa tuduhan salah.

   Karena itu, foto salinan yang dicetak belum tahan kolusi pada c = 3. Untuk foto, ketahanan kolusi hanya datang dari kanal latar, yaitu foto layar dan tangkapan layar.
4. **Foto yang terlalu terang juga menghapus pola latar** (banyak piksel kertas jenuh 255).
   * **Pemeriksaan.** Dekoder membandingkan energi pola asli dengan umpan, yaitu sel yang sama dengan tanda acak independen. Ujinya berupa uji z berpasangan atas selisih energi per bit dengan ambang tetap z = 3, sehingga peluang foto tanpa pola dianggap berpola sekitar 10^-3, berapa pun jumlah bit yang terlihat. Bila pola tidak lebih kuat dari derau, kanal latar tidak melaporkan apa pun dan catatan hasil menyebutnya. Uji ini tidak memakai kode penerima, jadi jauh kurang peka daripada skor tuduhan, dan pola yang lemah tidak selalu terdeteksi. Bila kanal geser saja tidak cukup, jawabannya "tidak cukup bukti".
   * **Dua gambar uji gagal di sini.** Satu tanpa pola sama sekali (51 % bit benar, setara tebakan). Satu lagi berpola lemah (65 % bit benar, z = 2,94, tepat di bawah ambang). Kami tidak menurunkan ambang setelah melihat hasil ini.
   * **Jaminan tuduhan salah tidak terpengaruh.** Bobot tidak pernah memakai kode penerima. Gerbang ini hanya mencegah derau mengencerkan bukti kanal geser.
5. **Geser baris rentan pada tangkapan layar beresolusi rendah**, karena penampil PDF membulatkan garis dasar ke piksel. Dekoder menaksir derau per jenis dan otomatis memberi bobot kecil; geser kata (horizontal) tetap terbaca.
6. **Kanal teks tidak aman terhadap lawan yang paham.** Simbol lebar-nol dan huruf Kiril dapat dibersihkan atau diubah. Lawan tidak dapat memakainya untuk memfitnah orang lain karena tidak tahu kode penerima lain, tetapi dapat menghapus bukti di kanal ini. Pencarian frasa lintas kata di penampil PDF dapat gagal pada salinan bertanda; pencarian satu kata tetap berfungsi.
7. **Kanari bergantung pada penampil.** Adobe Reader menghubungi alamat aksi pembuka, tetapi lebih dulu menampilkan peringatan izin kepada setiap pembuka, termasuk penerima sah, sehingga kanari mudah dikenali dan dibuang. Word mengambil gambar eksternal. Penampil peramban dan MuPDF tidak mengambil apa pun. Demo mensimulasikan pencarian DNS yang dilakukan penampil. Di dalam jaringan satuan, DNS internal harus menjawab zona kanari secara lokal agar penerima sah tidak memicu peringatan.
8. **Masukan PDF harus berlapis teks.** TAPAK menggambar ulang setiap glif. Gerbang visual menolak penerbitan bila gambar ulang tanpa tanda tidak identik dengan aslinya, misalnya karena font tidak dapat dipakai ulang. Induk DOCX juga diterima, tetapi salinannya hanya membawa karakter tak terlihat, huruf kembar Kiril, dan kanari.
9. **Koalisi melebihi c** tetap tidak menimbulkan tuduhan salah, tetapi tidak semua anggotanya tertangkap (sekitar 45 % pada 5 orang melawan kode c=3).
10. **Foto sintetis bukan foto ponsel sungguhan.** Simulator mencakup perspektif, pencahayaan, bayangan, blur, derau, penajaman, dan JPEG ganda. Simulator tidak memodelkan printer, jadi pola latar pada foto sintetis tetap utuh; hasil foto di README (benchmark 38 dari 40, gambar alur, tangkapan layar Lacak) karenanya lebih mirip foto layar daripada foto kertas cetak. Simulator juga tidak meniru pemrosesan gambar di kamera ponsel (pengurangan derau agresif, HDR, moire layar), dan kami belum menguji dengan ponsel sungguhan.
11. **Tanda air berbasis model (StegaStamp) belum dilatih.** Kerangkanya ada di `tapak/learned_wm/` (model, degradasi, pelatihan, ekspor ONNX) dan masih berisi TODO. Yang dipakai sekarang adalah dekoder korelasi.
12. **Konstanta 2 pi^2 dengan skor simetris belum terbukti untuk c kecil** (hanya asimtotik). Ini memengaruhi deteksi, bukan tuduhan salah; deteksi diukur dengan simulasi di [cara kerja](cara-kerja.md#angka-simulasi). Konstanta 100 tersedia sebagai pilihan konservatif.
13. **Batas tuduhan salah bersyarat dan berlaku per pelacakan.** Batas 10^-6 hanya berlaku bila rahasia kode tidak bocor dan catatan penerbitan tidak diubah. TAPAK menunjuk salinan dan penerima yang tercatat untuk salinan itu, bukan orang yang membocorkannya. Pelacakan tidak dicatat di registri, jadi melacak satu kebocoran berulang kali dengan potongan atau gabungan bukti yang berbeda menaikkan batas totalnya menjadi jumlah pelacakan dikali 10^-6.
