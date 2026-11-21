import io
import sqlite3
import unittest

from hdr10plus_index import SIDE_DATA, index_xml, timeline_frames


def metadata(average='1/5', reserved='0'):
    values = [
        ('application version','1'), ('num_windows','1'),
        ('targeted_system_display_maximum_luminance','1000/1'),
        ('maxscl','1/2'), ('maxscl','2/5'), ('maxscl','3/5'),
        ('average_maxrgb',average), ('num_distribution_maxrgb_percentiles','9'),
        ('fraction_bright_pixels','1/20'),
    ]
    for position,level in zip((1,5,10,25,50,75,90,95,99),
                              ('1/10',reserved,'255/100000','1/8','1/6','1/5','1/4','1/3','1/2')):
        values.extend([('distribution_maxrgb_percentage',str(position)),('distribution_maxrgb_percentile',level)])
    fields = ''.join(f'<side_datum key="{key}" value="{value}"/>' for key,value in values)
    return f'<side_data_list><side_data type="{SIDE_DATA}">{fields}</side_data></side_data_list>'


def sample(*frames):
    return io.BytesIO(('<ffprobe><frames>'+''.join(frames)+
                       '</frames><streams><stream time_base="1/1000"/></streams>'
                       '<format start_time="0.100"/></ffprobe>').encode())


class HDR10PlusIndexTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)

    def test_late_metadata_vfr_move_trim_and_duplicate(self):
        summary = index_xml(sample(
            '<frame pts="100" duration="20"/>',
            '<frame pts="120" duration="40">'+metadata()+'</frame>',
            '<frame pts="160" duration="20"/>',
            '<frame pts="180" duration="20">'+metadata('1/4')+'</frame>',
        ),self.db)
        self.assertEqual((summary['frames'],summary['dynamicFrames'],summary['rejectedFrames']),(4,2,0))
        rows = list(timeline_frames(self.db,position='2',start='.02',end='.1',speed='1',
                                    first=120,last=125,fps=60))
        self.assertEqual([row[:2] for row in rows],[(120,120),(121,120),(122,120),(123,160),(124,180)])
        self.assertEqual(rows[0][2],rows[1][2])
        self.assertIsNone(rows[3][2])
        self.assertNotEqual(rows[2][2],rows[4][2])
        fast = list(timeline_frames(self.db,position='0',start='.02',end='.1',speed='2',
                                    first=0,last=3,fps=60))
        self.assertEqual([row[1] for row in fast],[120,120,180])

    def test_invalid_metadata_never_reused(self):
        summary = index_xml(sample('<frame pts="100" duration="20">'+metadata('2/1')+'</frame>'),self.db)
        self.assertEqual((summary['dynamicFrames'],summary['rejectedFrames']),(0,1))
        with self.assertRaisesRegex(ValueError,'malformed'):
            list(timeline_frames(self.db,position=0,start=0,end='.02',speed=1,first=0,last=1,fps=60))

    def test_duplicate_presentation_timestamps_fail_index(self):
        with self.assertRaisesRegex(ValueError,'non-increasing'):
            index_xml(sample('<frame pts="100"/><frame pts="100"/>'),self.db)

    def test_reserved_distribution_value_preserved_but_blocks_reuse(self):
        summary = index_xml(sample('<frame pts="100" duration="20">'+metadata(reserved='1/2')+'</frame>'),self.db)
        self.assertEqual((summary['dynamicFrames'],summary['nonconformingDistributionFrames']),(1,1))
        self.assertIsNotNone(self.db.execute('SELECT metadata FROM frames').fetchone()[0])
        with self.assertRaisesRegex(ValueError,'nonconforming'):
            list(timeline_frames(self.db,position=0,start=0,end='.02',speed=1,first=0,last=1,fps=60))

    def test_cancelled_parse_is_not_a_complete_index(self):
        with self.assertRaisesRegex(ValueError,'cancelled'):
            index_xml(sample('<frame pts="100"/>'),self.db,lambda:True)
        self.assertIsNone(self.db.execute('SELECT data FROM summary').fetchone())
