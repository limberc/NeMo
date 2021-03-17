# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
# Copyright 2015 and onwards Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import os
import string
from pathlib import Path

import pynini
from data_loader_utils import get_abs_path
from pynini import Far
from pynini.examples import plurals
from pynini.lib import byte, pynutil, utf8

NEMO_DIGIT = byte.DIGIT
NEMO_NOT_QUOTE = pynini.difference(NEMO_CHAR, r'"').optimize()
NEMO_LOWER = pynini.union(*string.ascii_lowercase).optimize()
NEMO_UPPER = pynini.union(*string.ascii_uppercase).optimize()
NEMO_ALPHA = pynini.union(NEMO_LOWER, NEMO_UPPER).optimize()
NEMO_ALNUM = pynini.union(NEMO_DIGIT, NEMO_ALPHA).optimize()
NEMO_HEX = pynini.union(*string.hexdigits).optimize()
NEMO_NON_BREAKING_SPACE = u"\u00A0"
NEMO_SPACE = " "
NEMO_WHITE_SPACE = pynini.union(" ", "\t", "\n", "\r", u"\u00A0").optimize()
NEMO_NOT_SPACE = pynini.difference(NEMO_CHAR, NEMO_WHITE_SPACE).optimize()
NEMO_NOT_QUOTE = pynini.difference(NEMO_CHAR, r'"').optimize()

NEMO_PUNCT = pynini.union(*map(pynini.escape, string.punctuation)).optimize()
NEMO_GRAPH = pynini.union(NEMO_ALNUM, NEMO_PUNCT).optimize()

NEMO_SIGMA = pynini.closure(NEMO_CHAR)


delete_space = pynutil.delete(pynini.closure(NEMO_WHITE_SPACE))
insert_space = pynutil.insert(" ")
delete_extra_space = pynini.cross(pynini.closure(NEMO_WHITE_SPACE, 1), " ")


suppletive = pynini.string_file(get_abs_path("data/suppletive.tsv"))
# _v = pynini.union("a", "e", "i", "o", "u")
_c = pynini.union(
    "b", "c", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "q", "r", "s", "t", "v", "w", "x", "y", "z"
)
_ies = NEMO_SIGMA + _c + pynini.cross("y", "ies")
_es = NEMO_SIGMA + pynini.union("s", "sh", "ch", "x", "z") + pynutil.insert("es")
_s = NEMO_SIGMA + pynutil.insert("s")

graph_plural = plurals._priority_union(
    suppletive, plurals._priority_union(_ies, plurals._priority_union(_es, _s, NEMO_SIGMA), NEMO_SIGMA), NEMO_SIGMA
).optimize()

SINGULAR_TO_PLURAL = graph_plural
PLURAL_TO_SINGULAR = pynini.invert(graph_plural)


def get_plurals(fst):
    """
    Given singular returns plurals

    Args:
        fst: Fst

    Returns plurals to given singular forms
    """
    return SINGULAR_TO_PLURAL @ fst


def get_singulars(fst):
    """
    Given plural returns singulars

    Args:
        fst: Fst

    Returns singulars to given plural forms
    """
    return PLURAL_TO_SINGULAR @ fst


def convert_space(fst) -> pynini.FstLike:
    """
    Converts space to nonbreaking space.
    Used only in tagger grammars for transducing token values within quotes, e.g. name: "hello kitty"
    This is making transducer significantly slower, so only use when there could be potential spaces within quotes, otherwise leave it. 

    Args:
        fst: input fst

    Returns output fst where breaking spaces are converted to non breaking spaces
    """
    return fst @ pynini.cdrewrite(pynini.cross(NEMO_SPACE, NEMO_NON_BREAKING_SPACE), "", "", NEMO_SIGMA)


class GraphFst:
    """
    Base class for all grammar fsts.

    Args:
        name: name of grammar class
        kind: either 'classify' or 'verbalize'
    """

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = str
        self._fst = None

        self.far_path = Path(os.path.dirname(__file__) + '/grammars/' + kind + '/' + name + '.far')
        if self.far_exist():
            self._fst = Far(self.far_path, mode="r", arc_type="standard", far_type="default").get_fst()

    def far_exist(self) -> bool:
        """
        Returns true if FAR can be loaded
        """
        return self.far_path.exists()

    @property
    def fst(self) -> pynini.FstLike:
        return self._fst

    @fst.setter
    def fst(self, fst):
        self._fst = fst

    def add_tokens(self, fst) -> pynini.FstLike:
        """
        Wraps class name around to given fst

        Args: 
            fst: input fst
        
        Returns Fst
        """
        return pynutil.insert(f"{self.name} {{ ") + fst + pynutil.insert(" }")

    def delete_tokens(self, fst) -> pynini.FstLike:
        """
        Deletes class name wrap around output of given fst

        Args
            fst: input fst

        Returns Fst
        """
        res = (
            pynutil.delete(f"{self.name}")
            + delete_space
            + pynutil.delete("{")
            + delete_space
            + fst
            + delete_space
            + pynutil.delete("}")
        )
        return res @ pynini.cdrewrite(pynini.cross(u"\u00A0", " "), "", "", NEMO_SIGMA)


def add_arcs(graph: pynini.FstLike, node_a: int, node_b: int, labels: List[List[str]]):
    """
    Adds archs to a graph

    Args:
        graph: input fst
        node_a: start node index
        node_b: end node index
        labels: list of strings for input (output labels and/or weights) 
    """
    weight = 0
    for label in labels:
        if len(label) == 1:
            label = label[0]
            old_state = node_a
            for x in label[:-1]:
                new_state = graph.add_state()
                graph.add_arc(old_state, pynini.Arc(ord(x), ord(x), weight, new_state))
                old_state = new_state
            graph.add_arc(old_state, pynini.Arc(ord(label[-1]), ord(label[-1]), weight, node_b))
        elif len(label) == 2:
            old_state = node_a
            for x, y in itertools.zip_longest(label[0][:-1], label[1][:-1]):
                new_state = graph.add_state()
                x = 0 if x is None else ord(x)
                y = 0 if y is None else ord(y)
                graph.add_arc(old_state, pynini.Arc(x, y, weight, new_state))
                old_state = new_state
            x = label[0][-1]
            y = label[1][-1]
            x = 0 if x is None else ord(x)
            y = 0 if y is None else ord(y)
            graph.add_arc(old_state, pynini.Arc(x, y, weight, node_b))
        else:
            raise Exception