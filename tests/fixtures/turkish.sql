CREATE TABLE madde(madde_id INTEGER PRIMARY KEY,madde TEXT,birlesikler TEXT,telaffuz TEXT,lisan TEXT);
CREATE TABLE anlam(anlam_id INTEGER PRIMARY KEY,madde_id INTEGER,anlam_sira INTEGER,anlam TEXT,fiil INTEGER);
CREATE TABLE ozellik(ozellik_id INTEGER PRIMARY KEY,tam_adi TEXT,tur INTEGER);
CREATE TABLE anlam_ozellik(anlam_id INTEGER,ozellik_id INTEGER);
CREATE TABLE ornek(ornek_id INTEGER PRIMARY KEY,anlam_id INTEGER,ornek_sira INTEGER,ornek TEXT,yazar_id INTEGER,yazar_vd TEXT);
CREATE TABLE yazar(yazar_id INTEGER PRIMARY KEY,tam_adi TEXT);
CREATE TABLE atasozu(madde_id INTEGER PRIMARY KEY,madde TEXT);
CREATE TABLE madde_atasozu(madde_id INTEGER,atasozu_madde_id INTEGER);
INSERT INTO madde VALUES
 (1,'kitap','kitap kurdu',NULL,NULL),(2,'yaz',NULL,NULL,NULL),
 (3,'yazmak',NULL,NULL,NULL),(4,'yaz',NULL,NULL,NULL),
 (5,'çakmak',NULL,NULL,NULL),(6,'fark etmek',NULL,NULL,NULL),
 (7,'boş',NULL,NULL,NULL),(8,'IŞIK',NULL,NULL,NULL),(9,'İZ',NULL,NULL,NULL),
 (10,'kitap kurdu',NULL,NULL,NULL);
INSERT INTO anlam VALUES
 (11,1,2,'İkinci anlam.',0),(12,1,1,'Bir eser <script>.',0),
 (21,2,1,'Bir mevsim.',0),(31,3,1,'Yazı oluşturmak.',1),
 (41,4,1,'Aynı yazılış, ayrı madde.',0),(51,5,1,'Ateş yakma aracı.',0),
 (61,6,1,'Anlamak.',1),(81,8,1,'Aydınlık.',0),(91,9,1,'İşaret.',0),
 (101,10,1,'Çok okuyan kimse.',0);
INSERT INTO ozellik VALUES(1,'isim',3),(2,'mecaz',4);
INSERT INTO anlam_ozellik VALUES(12,1),(12,2),(21,1),(41,1),(51,1);
INSERT INTO yazar VALUES(1,'Örnek Yazar');
INSERT INTO ornek VALUES(1,12,1,'Örnek & alıntı.',1,''),(2,12,2,'İkinci örnek.',NULL,'');
INSERT INTO atasozu VALUES(6,'fark etmek');
INSERT INTO madde_atasozu VALUES(1,6);
INSERT INTO madde VALUES
 (11,'çocuk',NULL,NULL,NULL),(12,'kişi',NULL,NULL,NULL),
 (13,'kış',NULL,NULL,NULL),(14,'benzerlik',NULL,NULL,NULL);
INSERT INTO anlam VALUES
 (111,11,1,'Küçük yaştaki insan.',0),(121,12,1,'İnsan.',0),
 (131,13,1,'Soğuk mevsim.',0),(141,14,1,'Benzer olma durumu.',0);
INSERT INTO anlam_ozellik VALUES(111,1),(121,1),(131,1),(141,1);
