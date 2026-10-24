# Kalibrasi bobot geser kata pada bukti gambar

[Studi kalibrasi pola latar](../kalibrasi/README.md) menyisakan satu masalah: bit kelompok kata (kanal geser, skema v2) tetap terlalu yakin pada foto, foto ISP ponsel, foto monitor, foto cetakan, tangkapan simulator, dan tangkapan 28 sampai 48 dpi. Pada set ujinya, bobot di atas 0,999 salah 80 dari 2.781 pada foto dasar dan 92 dari 3.558 pada foto cetakan, padahal bobotnya hanya menjanjikan sekitar 0,2 salah. Karena itu batas deteksi dengan laju (1 - w)/2 ([batasan 12](../../docs/keamanan.md#batasan-12)) tidak berlaku untuk foto dan cetakan. Studi ini mencari penyebabnya, memilih model kelompok kata yang buta kode pada bukti pengembangan, lalu menjalankan bukti uji baru sekali.

Tidak ada ambang tuduhan, eps, aturan pembagian eps, atau aturan putusan yang berubah, dan tidak ada dekoder yang melihat kode penerima. Kode penerima hanya dipakai di sini untuk menghitung bit yang salah. Batas tuduhan salah tidak bergantung pada kalibrasi. Semua dokumen dan penerima fiktif; semua tangkapan, foto, dan cetakan sintetis.

## Penyebab (bukti pengembangan)

Bukti pengembangan adalah semua bukti gambar studi kalibrasi, kedua split-nya (keduanya sudah diukur dan dilaporkan di sana, jadi tidak ada yang ditahan di sini). Registrasi tersimpan setiap bukti dipakai lagi: halaman yang sama diukur ulang, dan dekoder sebelum studi ini mengulang setiap keluaran geser yang tersimpan (1.331 bukti gambar, 0 berbeda). Untuk salinan tunggal, tanda fisik setiap kelompok diketahui, jadi residu baris sebenarnya (setelah gangguan baris diproyeksikan keluar) dapat dibakukan dengan sigma yang ditaksir dekoder.

* **Ekor tebal pada foto dan cetakan.** Residu baku kelompok kata bervarians 1,7 sampai 1,8 dengan kurtosis 7 sampai 9 (Gauss: 3) pada foto dan foto cetakan, dan 4 % kelompok lebih dari 3 sigma (Gauss: 0,3 %). Pada foto tegak lurus (sudut 0) variansnya sekitar 1; makin miring, makin besar (sampai 5 pada satu foto 20 derajat). Kelompok yang bergeser lebih dari delta ke arah lain terbaca sebagai tanda yang yakin dan salah.
* **Kecocokan templat yang buruk.** Di dalam satu bukti, kelompok dengan korelasi puncak templat terendah (1 - puncak relatif terhadap median bukti, seperlima teratas) bervarians 2,6 kali dan 7 % di atas 3 sigma, seperlima terbaik 1,2 kali dan 2 %. Residu tidak berkorelasi antartetangga sebaris.
* **Tanda yang mengecil di resolusi rendah.** Dengan tanda yang benar, geseran terukur hanya 0,53 (20 sampai 30 dpi efektif), 0,65 (30 sampai 36), dan 0,69 (36 sampai 44) kali tanda yang diterbitkan, lalu sekitar 0,95 mulai 44 dpi. Dekoder memakai tanda penuh, jadi bobotnya terlalu besar di semua kelompok bobot rendah dan menengah.
* **Penguatan per bukti tidak dapat ditaksir.** Model yang menaksir penguatan tanda per bukti (EM atas tanda yang tersembunyi) justru lebih buruk (46 sel terlalu yakin, sebelumnya 34): dengan tanda tersembunyi, penguatan dan derau saling menggantikan.

## Kandidat dan pemilihan

Semua kandidat (`ch_shift.WORD_MODELS`) hanya mengubah LLR kelompok kata bukti gambar. Baris, medan halaman, kelompok yang dibuang, sigma, dan kekuatan (pemeriksaan pola penghapusan) tetap dari dekoder Gauss, dan PDF yang diteruskan didekode persis seperti sebelumnya. Model t: kemungkinan baris Student t dengan nu derajat kebebasan; offset dan kemiringan baris dicocokkan per pola tanda dengan kuadrat terkecil berbobot ulang; 2^g pola tetap dihitung semua; skala t ditaksir dengan EM atas semua baris. `redam`: di bawah 44 dpi efektif tanda dianggap 0,6 kali ukurannya. `puncak`: skala tiap kelompok sebanding dengan (1 - korelasi puncak) relatif terhadap median bukti, dibatasi 1/4 sampai 4, dipangkatkan 1 atau 0,5.

Prototipe di luar repositori menilai kalibrasi kelompok kata saja pada putaran 1 sampai 3 (penguatan per bukti; nu 2, 3, 4, dan pilihan nu per bukti; `redam`; `puncak`). Aturan pemilihan `kandidat.py` (`ATURAN`) ditulis setelah itu, sebelum putusan, peringatan, atau kalibrasi gabungan kandidat mana pun dihitung, dan dicatat di git sebelum bukti uji dibuat: (1) tidak ada tuduhan salah; (2) tidak ada salinan atau anggota koalisi yang disebut dekoder sebelumnya lalu hilang; (3) tidak ada pelacakan jujur yang mendapat peringatan baru; (4) sel terlalu yakin (kelas medium x kelompok bobot, P(Poisson(E) >= k) < 10^-4) dihitung untuk kelompok kata dan bacaan gabungan; (5) di antara kandidat yang lolos 1 sampai 3 dan punya lebih sedikit sel kata terlalu yakin daripada dekoder sebelumnya, sel kata ditambah sel gabungan paling sedikit.

HASIL_PEMILIHAN

## Hasil (set uji)

HASIL_UJI

## Yang tersisa

YANG_TERSISA

## Menjalankan

Dari akar repositori, dengan folder kerja studi kalibrasi (`$TAPAK_KALIBRASI_KERJA`, berisi terbitan, bukti, dan pengamatannya) dan folder kerja studi ini (`$TAPAK_GESER_KERJA`, bawaan `out/riset_geser`; besar, tidak di-commit; paling banyak 3 proses):

```bash
export PYTHONPATH=. TAPAK_KALIBRASI_KERJA=out/riset_kalibrasi TAPAK_GESER_KERJA=out/riset_geser
G=".venv/bin/python research/geser"
$G/kandidat.py nilai          # setiap kandidat pada setiap bukti pengembangan
$G/kandidat.py pilih          # aturan: hasil/pilihan.json
$G/ukur.py terbit && $G/ukur.py lacak     # set uji, sekali, dengan model pilihan
$G/ringkas.py --json          # hasil/ringkas_uji.json
```

`ukur.py lacak` menolak berjalan bila model kata bawaan dekoder (`ch_shift.IMAGE_WORD_MODEL`) bukan pilihan di `hasil/pilihan.json`, mencatat hash sumber dekoder di `hasil/uji_dekoder.json` sebelum pelacakan pertama, dan melewati bukti yang sudah tercatat bila diulang setelah terputus.
