import csv
import tempfile
import unittest
from pathlib import Path
from rsl_marc import parse,export_saved,decode_record
SOURCE=Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов/01008080457.mrc')

class Tests(unittest.TestCase):
    def test_fields(self):
        r=parse(SOURCE.read_bytes())
        self.assertEqual(r['year'],1887)
        self.assertEqual(r['date_literal'],'[1887]')
        self.assertEqual(r['scale_denominator'],1050000)
        self.assertEqual(r['author'],'')
        self.assertEqual(r['publisher'],'')
        self.assertEqual(r['manufacturer'],'Хромолитог. Д. Руднева')
        self.assertEqual(r['shelfmark'],'KGR Ко 102/IX-116')
        self.assertEqual(len(r['bbk']),2)
        self.assertEqual(len(r['notes']),3)

    def test_bad_lengths(self):
        raw=SOURCE.read_bytes()
        for data in [raw[:-1],raw+raw,raw[:24]+b'xxx'+raw[27:]]:
            with self.assertRaises(ValueError): decode_record(data)

    def test_date_not_from_control(self):
        raw=SOURCE.read_bytes().replace(b'[1887]',b'[????]')
        self.assertIsNone(parse(raw)['year'])

    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'out'; export_saved(SOURCE,p)
            self.assertEqual((p/SOURCE.name).read_bytes(),SOURCE.read_bytes())
            with (p/'notion_import.csv').open(encoding='utf-8-sig',newline='') as f:
                r=list(csv.DictReader(f))[0]
            self.assertEqual(r['Автор / составитель'],'')
            self.assertEqual(r['Год создания (верхняя)'],'1887')
            self.assertEqual(r['Масштаб (знаменатель)'],'1050000')
            self.assertEqual(r['Нулевой меридиан'],'')
            with self.assertRaises(FileExistsError): export_saved(SOURCE,p)

if __name__=='__main__': unittest.main()
