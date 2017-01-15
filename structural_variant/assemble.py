import networkx as nx
import itertools
import warnings
from .read_tools import CigarTools, nsb_align
from .constants import reverse_complement


class Contig:
    """
    """
    def __init__(self, sequence, score):
        self.seq = sequence
        self.remapped_reads = {}
        self.score = score
        self.alignments = None

    def __hash__(self):
        return hash(self.seq)

    def add_mapped_read(self, read, multimap=1):
        rc = reverse_complement(read)
        if rc in self.remapped_reads:
            self.remapped_reads[rc] = min(self.remapped_reads.get(rc, 1), 1 / multimap)
        else:
            self.remapped_reads[read] = min(self.remapped_reads.get(read, 1), 1 / multimap)

    def remap_score(self):
        return sum(self.remapped_reads.values())


class DeBruijnGraph(nx.DiGraph):
    """
    wrapper for a basic digraph
    enforces edge weights
    """

    def __init__(self, *pos, **kwargs):
        nx.DiGraph.__init__(self, *pos, **kwargs)
        self.edge_freq = {}

    def add_edge(self, n1, n2, freq=1):
        self.edge_freq[(n1, n2)] = self.edge_freq.get((n1, n2), 0) + freq
        nx.DiGraph.add_edge(self, n1, n2)

    def remove_edge(self, n1, n2):
        del self.edge_freq[(n1, n2)]
        nx.DiGraph.remove_edge(self, n1, n2)

    def trim_low_weight_tails(self, min_weight):
        """
        for any paths where all edges are lower than the minimum weight trim

        Args:
            min_weight (int): the minimum weight for an edge to be retained
        """
        for n in list(self.nodes()):
            if not self.has_node(n):
                continue
            # follow until the path forks or we run out of low weigh edges
            curr = n
            while self.degree(curr) == 1:
                if self.out_degree(curr) == 1:
                    curr, other = self.out_edges(curr)[0]
                    if self.edge_freq[(curr, other)] < min_weight:
                        self.remove_node(curr)
                        curr = other
                    else:
                        break
                elif self.in_degree(curr) == 1:
                    other, curr = self.in_edges(curr)[0]
                    if self.edge_freq[(other, curr)] < min_weight:
                        self.remove_node(curr)
                        curr = other
                    else:
                        break
                else:
                    break
        for n in list(self.nodes()):
            if not self.has_node(n):
                continue
            if self.degree(n) == 0:
                self.remove_node(n)


def digraph_connected_components(graph):
    """
    the networkx module does not support deriving connected
    components from digraphs (only simple graphs)
    this function assumes that connection != reachable
    this means there is no difference between connected components
    in a simple graph and a digraph

    Args:
        graph (networkx.DiGraph): the input graph to gather components from

    Returns:
        :class:`list` of :class:`list`: returns a list of compnents which are lists of node names
    """
    g = nx.Graph()
    for src, tgt in graph.edges():
        g.add_edge(src, tgt)
    for n in graph.nodes():
        g.add_node(n)
    return nx.connected_components(g)


def assemble(sequences, kmer_size=None, min_edge_weight=3, min_match_quality=0.95, min_read_mapping_overlap=None,
             min_contig_length=None):
    """
    for a set of sequences creates a DeBruijnGraph
    simplifies trailing and leading paths where edges fall
    below a weight threshold and the return all possible unitigs/contigs

    Args:
        sequences (:class:`list` of :class:`str`): a list of strings/sequences to assemble
        kmer_size (int): the size of the kmer to use
        min_edge_weight (int): applies to trimming (see desc)
        min_match_quality (float): percent match for re-aligned reads to contigs
        min_read_mapping_overlap (int): the minimum amount of overlap required when aligning reads to contigs

    Returns:
        :class:`list` of :class:`Contig`: a list of putative contigs
    """
    if len(sequences) == 0:
        return []
    min_seq = min([len(s) for s in sequences])
    if kmer_size is None:
        temp = int(min_seq * 0.75)
        if temp < 10:
            kmer_size = min(min_seq, 10)
        else:
            kmer_size = temp
    elif kmer_size > min_seq:
        kmer_size = min_seq
        warnings.warn(
            'cannot specify a kmer size larger than one of the input sequences. reset to {0}'.format(min_seq))
    min_read_mapping_overlap = kmer_size if min_read_mapping_overlap is None else min_read_mapping_overlap
    min_contig_length = min_seq + 1 if min_contig_length is None else min_contig_length
    assembly = DeBruijnGraph()

    for s in sequences:
        for kmer in kmers(s, kmer_size):
            l = kmer[:-1]
            r = kmer[1:]
            assembly.add_edge(l, r)

    if not nx.is_directed_acyclic_graph(assembly):
        NotImplementedError('assembly not supported for cyclic graphs')

    for s, t in sorted(assembly.edges()):
        f = assembly.edge_freq[(s, t)]
    # now just work with connected components
    # trim all paths from sources or to sinks where the edge weight is low
    assembly.trim_low_weight_tails(min_edge_weight)
    path_scores = {}  # path_str => score_int

    for component in digraph_connected_components(assembly):
        # since now we know it's a tree, the assemblies will all be ltd to
        # simple paths
        sources = set()
        sinks = set()
        for node in component:
            if assembly.degree(node) == 0:  # ignore singlets
                pass
            elif assembly.in_degree(node) == 0:
                sources.add(node)
            elif assembly.out_degree(node) == 0:
                sinks.add(node)
        if len(sources) * len(sinks) > 10:
            warnings.warn('source/sink combinations: {}'.format(len(sources) * len(sinks)))

        for source, sink in itertools.product(sources, sinks):
            for path in nx.all_simple_paths(assembly, source, sink):
                s = path[0] + ''.join([p[-1] for p in path[1:]])
                score = 0
                for i in range(0, len(path) - 1):
                    score += assembly.edge_freq[(path[i], path[i + 1])]
                path_scores[s] = max(path_scores.get(s, 0), score)
    # now map the contigs to the possible input sequences
    contigs = {}
    for seq, score in list(path_scores.items()):
        if seq not in sequences and len(seq) >= min_contig_length:
            contigs[seq] = Contig(seq, score)

    # remap the input reads
    for input_seq in sequences:
        maps_to = {}  # contig, score
        for contig in contigs.values():
            a = nsb_align(
                contig.seq,
                input_seq,
                min_overlap_percent=min_read_mapping_overlap / len(contig.seq)
            )
            if len(a) != 1:
                continue
            if CigarTools.match_percent(a[0].cigar) < min_match_quality:
                continue
            maps_to[contig] = a[0]
        for contig, read in maps_to.items():
            contig.add_mapped_read(read, len(maps_to.keys()))
    return list(contigs.values())


def kmers(s, size):
    """
    for a sequence, compute and return a list of all kmers of a specified size

    Args:
        s (str): the input sequence
        size (int): the size of the kmers

    Returns:
        :class:`list` of :class:`str`: the list of kmers

    Example:
        >>> kmers('abcdef', 2)
        ['ab', 'bc', 'cd', 'de', 'ef']
    """
    kmers = []
    for i in range(0, len(s)):
        if i + size > len(s):
            break
        kmers.append(s[i:i + size])
    return kmers