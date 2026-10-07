import unittest

from meikipop.ocr.context import ContextHit, hit_paragraphs, sentence_at, paddle_paragraphs, paddle_lines
from meikipop.ocr.interface import BoundingBox, Paragraph, Word


class ContextTests(unittest.TestCase):
    def test_japanese_sentence_includes_closing_quote_and_word_span(self):
        text = '前です。「猫が好きです！」次です。'
        start = text.index('猫')
        sentence, first, last = sentence_at(text, start, start + 1)
        self.assertEqual(sentence, '「猫が好きです！」')
        self.assertEqual(sentence[first:last], '猫')

    def test_turkish_sentence_and_decimal(self):
        text = 'İlk cümle. Bu araç 3.5 metre uzun! Son cümle.'
        start = text.index('araç')
        sentence, first, last = sentence_at(text, start, start + 4)
        self.assertEqual(sentence, 'Bu araç 3.5 metre uzun!')
        self.assertEqual(sentence[first:last], 'araç')

    def test_truncated_visible_text_is_preserved(self):
        text = 'çünkü oğlum bugün'
        self.assertEqual(ContextHit('oğlum', text, 6, 11).sentence, (text, 6, 11))

    def test_hit_preserves_spaces_and_repeated_words(self):
        box = BoundingBox(.6, .5, .2, .2)
        paragraph = Paragraph('bir kitap bir kitap.', [Word('bir', ' ', BoundingBox(.1,.5,.1,.2)),
                              Word('kitap', ' ', BoundingBox(.3,.5,.1,.2)),
                              Word('bir', ' ', BoundingBox(.45,.5,.1,.2)), Word('kitap.', '', box)], box, False)
        hit = hit_paragraphs([paragraph], (.6,.5), 'tr')
        self.assertEqual(hit.query, 'kitap')
        self.assertEqual(hit.start, 14)
        self.assertEqual(hit.text[hit.start:hit.end], 'kitap')

    def test_japanese_native_word_boxes_interpolate(self):
        box = BoundingBox(.5,.5,.8,.2)
        paragraph = Paragraph('本を読む。', [Word('本を読む。','',box)], box, False)
        hit = hit_paragraphs([paragraph], (.5,.5), 'ja')
        self.assertEqual(hit.query, '読む。')
        self.assertEqual(hit.start, 2)

    def test_japanese_small_character_gaps_select_nearest_without_cursor_nudge(self):
        for vertical in (False, True):
            boxes = [BoundingBox(.5, center, .2, .18) if vertical else
                     BoundingBox(center, .5, .18, .2) for center in (.3, .5)]
            paragraph = Paragraph('日本', [Word('日', '', boxes[0]), Word('本', '', boxes[1])],
                                  BoundingBox(.5, .5, .8, .8), vertical)
            for position, expected in ((.395, 0), (.405, 1), (.415, 1)):
                with self.subTest(vertical=vertical, position=position):
                    point = (.5, position) if vertical else (position, .5)
                    hit = hit_paragraphs([paragraph], point, 'ja')
                    self.assertIsNotNone(hit)
                    self.assertEqual(hit.start, expected)
                    self.assertEqual(hit.query, paragraph.full_text[expected:])

    def test_character_gap_hit_keeps_original_offsets(self):
        words = [Word('本', '', BoundingBox(.3, .5, .18, .2), 2),
                 Word('本', '', BoundingBox(.5, .5, .18, .2), 3)]
        paragraph = Paragraph('前。本本', words, BoundingBox(.4, .5, .4, .2), False)
        hit = hit_paragraphs([paragraph], (.405, .5), 'ja')
        self.assertEqual(hit.start, 3)
        self.assertEqual(hit.sentence[0], '本本')

    def test_character_gaps_do_not_bridge_lines_large_spaces_or_spaced_words(self):
        first = BoundingBox(.3, .5, .18, .2)
        cases = [(BoundingBox(.5, .5, .18, .2), (.4, .65), 'ja'),
                 (BoundingBox(.5, .8, .18, .2), (.4, .5), 'ja'),
                 (BoundingBox(.7, .5, .18, .2), (.5, .5), 'ja'),
                 (BoundingBox(.5, .5, .18, .2), (.405, .5), 'tr')]
        for second, point, language in cases:
            with self.subTest(second=second, point=point, language=language):
                paragraph = Paragraph('日本', [Word('日', '', first), Word('本', '', second)],
                                      BoundingBox(.5, .5, .8, .8), False)
                self.assertIsNone(hit_paragraphs([paragraph], point, language))

    def test_paddle_adapter_preserves_original_context(self):
        paragraphs = paddle_paragraphs([dict(rec_texts=['Bu araç yeni.'], text_word=[['Bu','araç','yeni.']],
                                             text_word_boxes=[[[0,0,20,20],[30,0,70,20],[80,0,120,20]]])], 120, 20)
        hit = hit_paragraphs(paragraphs, (.4,.5), 'tr')
        self.assertEqual(hit.query, 'araç')
        self.assertEqual(hit.sentence[0], 'Bu araç yeni.')

    def test_paddle_actual_accent_fragments_form_one_unicode_word(self):
        import numpy as np
        # Actual grouping from PaddleX 3.7 BaseRecLabelDecode.get_word_info.
        result = dict(rec_texts=['Bu araç yeni.'], text_word=[['Bu', ' ', 'ara', 'ç ', 'yeni', '.']],
                      text_word_boxes=[np.array([[0,0,20,20], [20,0,30,20], [30,0,60,20],
                                                [60,0,80,20], [80,0,120,20], [120,0,130,20]])])
        paragraphs = paddle_paragraphs([result], 130, 20)
        for x in (35, 65):
            hit = hit_paragraphs(paragraphs, (x / 130, .5), 'tr')
            self.assertEqual(hit.query, 'araç')
            self.assertEqual(hit.text[hit.start:hit.end], 'araç')
        for x in (25, 75, 125):
            self.assertIsNone(hit_paragraphs(paragraphs, (x / 130, .5), 'tr'))

    def test_paddle_apostrophes_repeated_words_and_symbol_runs_keep_offsets(self):
        text = 'İstanbul’da kitap, kitap!'
        fragments = ['İ', 'stanbul', '’', 'da', ' ', 'kitap', ', ', 'kitap', '!']
        boxes, offset = [], 0
        for fragment in fragments:
            boxes.append([offset * 10, 0, (offset + len(fragment)) * 10, 20])
            offset += len(fragment)
        result = dict(rec_texts=[text], text_word=[fragments], text_word_boxes=[boxes])
        words = list(paddle_lines([result]))[0][1]
        self.assertEqual([(word, start, end) for word, start, end, _ in words],
                         [('İstanbul’da', 0, 11), ('kitap', 12, 17), ('kitap', 19, 24)])
        # Paddle puts all three characters into a single non-ASCII symbol run.
        symbol_run = dict(rec_texts=['ı ı'], text_word=[['ı ı']], text_word_boxes=[[[0, 0, 30, 20]]])
        paragraphs = paddle_paragraphs([symbol_run], 30, 20)
        self.assertEqual(hit_paragraphs(paragraphs, (25 / 30, .5), 'tr').start, 2)
        self.assertIsNone(hit_paragraphs(paragraphs, (.5, .5), 'tr'))

    def test_paddle_wraps_continue_visible_sentence_without_merging_columns(self):
        result = dict(rec_texts=['Bu araç', 'çok güzel.', 'Başka sütun.', 'Ayrı blok.'],
                      text_word=[['Bu ', 'araç'], ['çok ', 'güzel.'], ['Başka ', 'sütun.'], ['Ayrı ', 'blok.']],
                      text_word_boxes=[[[0,0,30,20],[30,0,100,20]],
                                       [[0,28,40,48],[40,28,100,48]],
                                       [[200,0,240,20],[240,0,300,20]],
                                       [[0,100,40,120],[40,100,100,120]]])
        paragraphs = paddle_paragraphs([result], 300, 120)
        self.assertEqual(len(paragraphs), 3)
        hit = hit_paragraphs(paragraphs, (60 / 300, 38 / 120), 'tr')
        self.assertEqual(hit.query, 'güzel')
        self.assertEqual(hit.sentence[0], 'Bu araç\nçok güzel.')
        self.assertEqual(hit.text[hit.start:hit.end], 'güzel')
        self.assertEqual(hit_paragraphs(paragraphs, (260 / 300, 10 / 120), 'tr').sentence[0], 'Başka sütun.')

    def test_paddle_missing_invalid_boxes_do_not_invent_partial_words(self):
        result = dict(rec_texts=['araç yeni'], text_word=[['ara', 'ç ', 'yeni']],
                      text_word_boxes=[[[0,0,30,20],[30,0,float('nan'),20],[50,0,90,20]]])
        words = list(paddle_lines([result]))[0][1]
        self.assertEqual([word[0] for word in words], ['yeni'])
        self.assertEqual(paddle_paragraphs([dict(rec_texts=[], text_word=[], text_word_boxes=[])], 100, 50), [])
        with self.assertRaises(ValueError):
            paddle_paragraphs([], 0, 50)

    def test_paddle_repeated_word_after_missing_box_keeps_exact_offset(self):
        result = dict(rec_texts=['kitap kitap'], text_word=[['kitap', ' ', 'kitap']],
                      text_word_boxes=[[[0,0,0,20],[50,0,60,20],[60,0,110,20]]])
        paragraphs = paddle_paragraphs([result], 110, 20)
        hit = hit_paragraphs(paragraphs, (80 / 110, .5), 'tr')
        self.assertEqual(hit.start, 6)
        self.assertEqual(hit.end, 11)


if __name__ == '__main__':
    unittest.main()
