import unittest

from mavis.annotate.variant import IndelCall, call_protein_indel

from .mock import Mock, MockFunction


class TestIndelCall(unittest.TestCase):

    def test_deletion(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(4, indel.last_aligned)
        self.assertEqual(8, indel.next_aligned)
        self.assertEqual('ghj', indel.del_seq)
        self.assertEqual('', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_insertion(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfmmmghjkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(4, indel.last_aligned)
        self.assertEqual(5, indel.next_aligned)
        self.assertEqual('', indel.del_seq)
        self.assertEqual('mmm', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_dup(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfsdfghjkl'
        indel = IndelCall(refseq, mutseq)
        print(indel)
        self.assertEqual(4, indel.last_aligned)
        self.assertEqual(2, indel.next_aligned)
        self.assertEqual('', indel.del_seq)
        self.assertEqual('sdf', indel.ins_seq)
        self.assertTrue(indel.is_dup)

    def test_delins(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfmmmkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(4, indel.last_aligned)
        self.assertEqual(8, indel.next_aligned)
        self.assertEqual('ghj', indel.del_seq)
        self.assertEqual('mmm', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_delete_start(self):
        refseq = 'asdfghjkl'
        mutseq = 'fghjkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(-1, indel.last_aligned)
        self.assertEqual(4, indel.next_aligned)
        self.assertEqual('asd', indel.del_seq)
        self.assertEqual('', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_delete_end(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfgh'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(6, indel.last_aligned)
        self.assertEqual(-1, indel.next_aligned)
        self.assertEqual('jkl', indel.del_seq)
        self.assertEqual('', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_ins_start(self):
        refseq = 'asdfghjkl'
        mutseq = 'mmasdfghjkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(-1, indel.last_aligned)
        self.assertEqual(1, indel.next_aligned)
        self.assertEqual('', indel.del_seq)
        self.assertEqual('mm', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_ins_end(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfghjklmmm'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(9, indel.last_aligned)
        self.assertEqual(-1, indel.next_aligned)
        self.assertEqual('', indel.del_seq)
        self.assertEqual('mmm', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_delins_start(self):
        refseq = 'asdfghjkl'
        mutseq = 'mmfghjkl'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(-1, indel.last_aligned)
        self.assertEqual(4, indel.next_aligned)
        self.assertEqual('asd', indel.del_seq)
        self.assertEqual('mm', indel.ins_seq)
        self.assertFalse(indel.is_dup)

    def test_delins_end(self):
        refseq = 'asdfghjkl'
        mutseq = 'asdfghjmmm'
        indel = IndelCall(refseq, mutseq)
        self.assertEqual(7, indel.last_aligned)
        self.assertEqual(-1, indel.next_aligned)
        self.assertEqual('kl', indel.del_seq)
        self.assertEqual('mmm', indel.ins_seq)
        self.assertFalse(indel.is_dup)


class TestHgvsProteinNotation(unittest.TestCase):

    def test_homopolymer(self):
        indel = IndelCall('ASDFGHJKKLQWERTYUIOP', 'ASDFGHJKKKKLQWERTYUIOP').hgvs_protein_notation()
        self.assertEqual('p.K8_K9dupKK', indel)

    def test_dup(self):
        indel = IndelCall('ASDFGHJKL', 'ASDFSDFGHJKL').hgvs_protein_notation()
        self.assertEqual('p.S2_F4dupSDF', indel)


class TestCallProteinIndel(unittest.TestCase):

    def test_insertion(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKIIILQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.K8_L9insIII', notation)

    def test_deletion(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.K8_L9delKL', notation)

    def test_synonymous(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual(None, notation)

    def test_delins(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJIIIQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.K8_L9delKLinsIII', notation)

    def test_transcript_name(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name=None, reference_object=Mock(name='reft'))
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJIIIQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('reft:p.K8_L9delKLinsIII', notation)

    def test_delete_start(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('FGHJKLQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.A1_D3delASD', notation)

    def test_delete_single_aa_start(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('SDFGHJKLQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.A1delA', notation)

    def test_delete_end(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYU'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.I17_P19delIOP', notation)

    def test_delete_single_aa_end(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIO'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual('ref:p.P19delP', notation)

    def test_ins_start(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('IIASDFGHJKLQWERTYUIOP'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual(None, notation)

    def test_ins_end(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name='ref')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOPII'))
        notation = call_protein_indel(ref_translation, mut_translation)
        self.assertEqual(None, notation)

    def test_no_reference_obj(self):
        ref_translation = Mock(get_aa_seq=MockFunction('ASDFGHJKLQWERTYUIOP'), name=None, reference_object='thing')
        mut_translation = Mock(get_aa_seq=MockFunction('ASDFGHJIIIQWERTYUIOP'))
        with self.assertRaises(AttributeError):
            call_protein_indel(ref_translation, mut_translation)