import random
import numpy as np
from collections import defaultdict, Counter
from .util import debug

class IncrementalMoveCache():
	'''
	Facilitates the implementation of "compound moves".

	Purpose is to enable incremental updates to the list of "moves" that can
	occur to the state.  Attempts to deal with higher-order interactions (i.e.
	conflicting Kinds for the same Move) in a manner which avoids favoring
	either Kind over the other.
	'''
	def __init__(self):
		self.__kindset = ReverseDict() # { move: kindset }

	def add(self, move, kind):
		# rip the move out
		kindset = self.__kindset.pop(move, frozenset())

		if kind in kindset:
			self.__kindset[move] = kindset # restore old state...
			raise ValueError("kind already present")

		# put it back in with one additional kind
		kindset |= set([kind])
		self.__kindset[move] = kindset

	def clear_one(self, move, kind):
		# rip the move out
		kindset = self.__kindset.pop(move, frozenset())

		if kind not in kindset:
			self.__kindset[move] = kindset # restore old state...
			raise ValueError("kind not present")

		# put it back in with one less kind
		kindset -= set([kind])
		if kindset:
			self.__kindset[move] = kindset

	def clear_all(self, move):
		self.__kindset.pop(move, frozenset())

	def has_move(self, move):
		return move in self.__kindset

	def randomly_decided_counts(self):
		'''
		Obtain a ``dict`` of ``{kind: count}``

		Each move is only counted once across all counts.
		Moves associated with multiple Kinds will be randomly distributed
		across those kinds.

		Return value is ``(counts, sources)``, where ``counts`` is a dict
		of ``{kind: count}``, and ``sources`` is an object needed by
		``pop_random_of_kind``.
		'''
		out = Counter()
		sources = defaultdict(Counter)
		for (kindset, count) in self.undecided_counts().items():
			# Total occurrences of each number 1-n after 'count' throws of an n-sided die
			counts = np.random.multinomial(count, [1./len(kindset)]*len(kindset))

			for (k,c) in zip(kindset, counts):
				out[k] += c
				sources[k][kindset] += c
		return (out, sources)

	def random_by_kind(self, kind, sources, check_total=None):
		'''
		Choose a random move associated with a given kind.

		The intended usage is as follows:
		* Use ``randomly_decided_counts`` to determine a fixed distribution of
		  kinds.  (this will also give you ``sources``)
		* Choose a kind by a weighted choice (multiplying each kind's weight
		  by its count)
		* Use ``random_by_kind``, providing ``sources``.
		  (sources is needed to ensure the probability distribution for the chosen
		   element is consistent with the previously chosen distribution of kinds)
		'''
		kindsets, counts = zip(*sources[kind].items())

		total = sum(counts)
		if check_total is not None:
			assert check_total == total, "mismatched total; bad sources?"

		# p = probability that an element came from a specific kindset, given that
		#     it was decided (in `randomly_decided_counts()`) to have this kind.
		kindset = np.random.choice(kindsets, p=[x/total for x in counts])
		return self.random_by_kindset(kindset)

	def random_by_kindset(self, kindset):
		'''
		Choose a random Move which is associated with all of the kinds provided (and only those).
		'''
		return self.__kindset.get_random_key(kindset)

	def undecided_counts(self):
		'''
		Obtain a ``dict`` of ``{frozenset(kinds): count}``

		Far more efficient than ``{ks:len(ms) for (ks,ms) in self.undecided_sets()}``,
		assuming there are many moves with the same kindset.
		'''
		return self.__kindset.value_counts()

	def undecided_sets(self):
		'''
		Obtain a ``dict`` of ``{frozenset(kinds): set(moves)}``

		Each move is only included once across all sets.
		A Move associated with multiple Kinds will be counted under a key with the
		frozenset of those kinds.

		Note that using this method largely defeats the purpose of IncrementalMoveCache,
		because it must iterate over all moves. The method exists only for testing purposes.
		'''
		return {ks:set(vs) for (ks,vs) in self.__kindset.value_iters().items()}


class ReverseDict:
	'''
	Provides a many-to-one association with value lookup.

	A ``dict`` that also keeps track of the list of keys sharing each value.

	Methods are provided for O(1) retrieval of an arbitrary or random key by value.

	``ReverseDict(...)`` takes any arguments in the forms accepted by ``dict(...)``.
	'''
	def __init__(self, *args, **kw):
		# The choice to use lists instead of sets for __keys pretty much all comes
		# down to the ``random_key`` methods; there is, simply put, no way to
		# choose a random element from a set. (``set.pop`` is NOT random!)

		# Were it not for this one absolutely critical design constraint,
		# we could do away with ``self.__index`` entirely.
		self.__index = {}  # {(key,value): index of key in __keys[value]}
		self.__value = {}  # {key: value}
		self.__keys = {} # {value: [keys]}

		# behave like dict constructor
		if args and isinstance(args[0], ReverseDict):
			(d,*rest) = args
			args = (d.items(),) + tuple(rest)
		for (k,v) in dict(*args, **kw).items():
			self.__setitem__(k, v)

	def lookup_keys(self, value):
		''' Iterate through all keys for a value. '''
		return self.__keys.get(value, []).__iter__()

	# common methods for containers
	def __len__(self): return self.__value.__len__()
	def __iter__(self): return self.__value.__iter__()
	def __contains__(self, key): return self.__value.__contains__(key)
	def __nonzero__(self): return self.__value.__nonzero__()

	# operators
	def __eq__(self, other):
		return isinstance(other, ReverseDict) and self.__value.__eq__(other.__value)

	# indexing
	def __getitem__(self, key):
		return self.__value.__getitem__(key)

	def __delitem__(self, key):
		if key in self: self.__delete_key(key)
		else: raise KeyError

	def __setitem__(self, key, value):
		# clean out old value first
		if key in self.__value:
			self.__delete_key(key)

		self.__value[key] = value

		if value not in self.__keys:
			self.__keys[value] = []

		assert (key,value) not in self.__index
		self.__index[(key,value)] = len(self.__keys[value])
		self.__keys[value].append(key)

	def get(self, key, default=None):
		''' Obtain a value by key or get a default value '''
		return self.__value.get(key, default)

	def items(self):
		''' Iterate through (key,value) pairs. '''
		return self.__value.items()

	__POP_NO_DEFAULT = object()
	def pop(self, key, default=__POP_NO_DEFAULT):
		''' Remove and obtain a value by key. '''
		if key in self.__value:
			value = self.__value[key]
			self.__delete_key(key)
			return value
		else:
			if default is self.__POP_NO_DEFAULT:
				raise KeyError
			return default
		assert False, "unreachable"

	# a much more rigorous equality test than __eq__ which
	# also looks at all of the redundant data structures
	#
	# Expects to only be run in debug mode.  Code outside of tests
	# can ensure this is held by doing 'assert obj.debug_validate(other)'
	# (the method always returns True for precisely this purpose)
	def debug_validate(self, correct):
		# FIXME this method contains both self-integrity tests and comparisons
		#  against another object, which feels like conflating goals.
		# However, it is like this because I want these self-integrity tests
		# to run during unittests

		# compare to a gold standard
		assert self.__value == correct.__value
		def comparable_keys(obj):
			# canonicalize the form of obj.__keys.
			# keep in mind we only require keys and values
			#  to be hashable/equatable, not orderable.
			return {v:set(ks) for (v,ks) in self.__keys.items()}
		assert comparable_keys(self) == comparable_keys(correct)

		# address the above note by further ensuring __keys has no dupes
		all_keys = list(flat(self.__keys.values()))
		assert len(all_keys) == len(set(all_keys))

		# check integrity of index lookup
		for (value,keys) in self.__keys.items():
			assert keys, 'empty key list not deleted'
			for (idx,key) in enumerate(keys):
				assert self.__index[(key,value)] == idx

		return True

	def pop_arbitrary_key(self, value):
		''' O(1) retrieval and removal of an arbitrarily chosen key for a given value. '''
		if value not in self.__keys:
			raise KeyError
		key = self.__keys[value][0]
		self.__delete_key(key)
		return key

	def pop_random_key(self, value, rng=random):
		''' O(1) retrieval and removal of a randomly chosen key for a given value. '''
		key = self.get_random_key(value, rng)
		self.__delete_key(key)
		return key

	def get_random_key(self, value, rng=random):
		''' O(1) retrieval of a randomly chosen key for a given value. '''
		return rng.choice(self.__keys[value])

	def value_counts(self):
		'''
		Get a ``collections.Counter`` giving occurrences of each value.

		Complexity is O(len(output)), i.e. the number of *unique* values
		in the dictionary.
		'''
		return Counter({value:len(keys) for (value,keys) in self.__keys.items()})

	def value_iters(self):
		'''
		Get a dict ``{value: iter of keys}`` giving all keys for each value.

		One should assume that any modification to a ReverseDict invalidates all
		of the iterators.
		'''
		return Counter({value:keys.__iter__() for (value,keys) in self.__keys.items()})

	# Remove a key and all associated data
	def __delete_key(self, key):

		value = self.__value[key]
		index = self.__index[(key,value)]

		# __keys is updated by swap removal.
		# At most one element will be displaced by this,
		#  whose index must be updated.
		displaced = self.__keys[value][-1]
		popped    = pop_n_swap(self.__keys[value], index)
		assert popped == key

		# Order here ensures correctness in the case where displaced == key
		# (in which case we want no entry to remain in index)
		self.__index[(displaced,value)] = index
		del self.__value[key]
		del self.__index[(key,value)]

		# cleanup empty lists
		if not self.__keys[value]:
			del self.__keys[value]

def pop_n_swap(seq, i):
	'''
	O(1) removal by index of a list element, moving the last one into its place.
	'''
	(seq[i], seq[-1]) = (seq[-1], seq[i]) # seems to work fine for i == -1
	return seq.pop()

import unittest
class ReverseDictTests(unittest.TestCase):

	def setUp(self):
		self.empty = ReverseDict()
		self.three_dict = {'a': 'shared', 'b': 'shared', 'c': 'unique'}
		self.three = ReverseDict(self.three_dict)
		self.four_dict = {'a': 'shared', 'b': 'shared', 'c': 'unique', 'd': 'third'}
		self.four = ReverseDict(self.four_dict)
		self.fourB_dict = {'a': 'shared', 'b': 'third', 'c': 'unique', 'd': 'third'}
		self.fourB = ReverseDict(self.fourB_dict)

	def test_construction(self):
		from itertools import permutations

		# a bunch of identical fellows through various methods
		a = ReverseDict(self.three_dict)   # (dict)
		b = ReverseDict(**self.three_dict) # (key=value, ...)
		c = ReverseDict(a)                 # (ReverseDict)
		d = ReverseDict(self.three_dict.items()) # iterable of (key,value)
		for s,t in permutations([a,b,c,d], r=2):
			assert s.debug_validate(t)

	def test_delegated(self):
		# __len__
		self.assertEqual(len(self.empty), 0)
		self.assertEqual(len(self.three), 3)
		# __iter__
		self.assertSetEqual(set(self.empty), set())
		self.assertSetEqual(set(self.three), set('abc'))
		# __contains__
		assert 'a' in self.three
		assert 'shared' not in self.three
		assert 'a' not in self.empty
		# __nonzero__
		assert not self.empty
		assert self.three
		# items
		self.assertDictEqual(dict(self.empty.items()), {})
		self.assertDictEqual(dict(self.three.items()), self.three_dict)
		# get
		self.assertEqual(self.empty.get('a'), None)
		self.assertEqual(self.empty.get('a',3), 3)
		self.assertEqual(self.three.get('b',4), 'shared')

	def test_value_counts(self):
		self.assertDictEqual(self.empty.value_counts(), {})
		self.assertDictEqual(self.three.value_counts(), {'shared': 2, 'unique': 1})

	def test_get_random_key(self):
		self.assertRaises(KeyError, self.empty.get_random_key, 'foo')
		self.assertRaises(KeyError, self.three.get_random_key, 'foo')

		picks = [self.three.get_random_key('shared') for _ in range(100)]
		self.assertSetEqual(set(picks), set('ab'))

		picks = [self.three.get_random_key('unique') for _ in range(100)]
		self.assertSetEqual(set(picks), set('c'))

	def test_getitem(self):
		self.assertRaises(KeyError, self.three.__getitem__, 'w')
		self.assertEqual(self.three['b'], 'shared')

	def test_setitem(self):
		assert len(self.three) == 3
		self.assertRaises(AssertionError, self.three.debug_validate, self.four)

		# __setitem__ - key not present
		self.three['d'] = 'third'
		assert len(self.three) == 4
		assert self.three.debug_validate(self.four)

		# __setitem__ - key already present
		self.assertRaises(AssertionError, self.three.debug_validate, self.fourB)
		self.three['b'] = 'third'
		assert len(self.three) == 4
		assert self.three.debug_validate(self.fourB)

	def test_delitem(self):
		# delete only key with value
		self.assertRaises(AssertionError, self.four.debug_validate, self.three)
		del self.four['d']
		assert self.four.debug_validate(self.three)
		self.assertSetEqual(set(self.four.value_counts()), set(['shared','unique']))

		# delete one key when multiple exist for value
		del self.four['a']
		self.assertSetEqual(set(self.four.value_counts()), set(['shared','unique']))
		assert self.four.debug_validate(ReverseDict({ 'b': 'shared', 'c': 'unique' }))

		# delete non-existing
		self.assertRaises(KeyError, self.four.__delitem__, 'w')

	def test_del_swap_remove(self):
		# NOTE: test assumes that the order of __keys is deterministic for
		#  a fixed sequence of setitems

		# construct a ReverseDict like self.three, but do it manually to ensure
		#  deterministic order of keys
		def make_new_dict(a=True, b=True):
			d = ReverseDict()
			if a: d['a'] = 'shared'
			if b: d['b'] = 'shared'
			d['c'] = 'unique'
			return d

		# One of these will internally perform a swap-removal, the other will not.
		# Doesn't matter which is which; we just want both cases to work correctly.
		d_a = make_new_dict()
		del d_a['a']
		assert d_a.debug_validate(make_new_dict(a=False))

		d_b = make_new_dict()
		del d_b['b']
		assert d_b.debug_validate(make_new_dict(b=False))

	def test_lookup_keys(self):
		keys = sorted(self.three.lookup_keys('shared'))
		self.assertListEqual(keys, ['a','b'])
		keys = sorted(self.three.lookup_keys('unique'))
		self.assertListEqual(keys, ['c'])
		keys = sorted(self.three.lookup_keys('foo'))
		self.assertListEqual(keys, [])

	def test_pop(self):
		# Missing keys, with/without defaults
		self.assertRaises(KeyError, self.three.pop, 'w')
		self.assertEqual(self.three.pop('w', None), None)
		self.assertEqual(self.three.pop('w', 7), 7)

		self.assertEqual(self.three.pop('b'), 'shared')
		self.assertEqual(self.three.pop('c'), 'unique')
		self.assertEqual(self.three.pop('a'), 'shared')
		assert self.three.debug_validate(self.empty)


	def do_pop_xxx_keys(self, meth):
		self.assertRaises(KeyError, meth, self.empty, 'foo')
		self.assertRaises(KeyError, meth, self.three, 'foo')
		popped = [
			meth(self.three, 'shared'),
			meth(self.three, 'shared'),
			meth(self.three, 'unique'),
		]
		self.assertSetEqual(set(popped[:2]), set('ab'))
		self.assertEqual(set(popped[2]), set('c'))
		assert self.three.debug_validate(self.empty)

	def test_pop_random_key(self):
		self.do_pop_xxx_keys(ReverseDict.pop_random_key)

	def test_pop_arbitrary_key(self):
		self.do_pop_xxx_keys(ReverseDict.pop_arbitrary_key)


class IncrementalMoveCacheTests(unittest.TestCase):

	def make_mc(self, **contents):
		from itertools import product

		mc = IncrementalMoveCache()
		for (kinds, moves) in contents.items():
			for (kind, move) in product(kinds, moves):
				mc.add(move, kind)

		self.validate(mc, **contents)
		return mc

	def validate(self, mc, **expected_contents):
		expected = {}
		for (kinds, moves) in expected_contents.items():
			expected[frozenset(kinds)] = set(moves)

		self.assertDictEqual(mc.undecided_sets(), expected)

	def test_add(self):
		# empty
		mc = IncrementalMoveCache()
		self.validate(mc)

		# brand new move with brand new kind
		mc.add('a', 'A')
		self.validate(mc, A='a')

		# brand new move with old kind
		mc.add('b', 'A')
		self.validate(mc, A='ab')

		# add new kind to existing move
		mc.add('a', 'B')
		self.validate(mc, AB='a', A='b')

		# two guys with a shared kindset
		mc.add('b', 'B')
		self.validate(mc, AB='ab')

	def test_clear_one(self):
		mc = self.make_mc(AB='ab')

		# clear one kind from move with many
		mc.clear_one('a', 'A')
		self.validate(mc, AB='b', B='a')

		# clear only kind for move
		mc.clear_one('a', 'B')
		self.validate(mc, AB='b')

	def test_mutation_errors(self):
		mc = self.make_mc(AB='b', A='a')
		self.assertRaises(ValueError, mc.add, 'b', 'A') # kind already there
		self.assertRaises(ValueError, mc.clear_one, 'b', 'C') # move present, but without kind
		self.assertRaises(ValueError, mc.clear_one, 'a', 'C') # move not present
		# make sure nothing changed
		self.validate(mc, AB='b', A='a')

	def test_validate(self):
		# make sure validate isn't trivially returning true
		mc = self.make_mc(AB='b', A='a')
		self.assertRaises(AssertionError, self.validate, mc, AB='b', A='d')
		self.assertRaises(AssertionError, self.validate, mc, B='b', A='a')

	def test_clear_all(self):
		mc = self.make_mc(AB='b', A='a')

		# clear move with multiple kinds
		mc.clear_all('b')
		self.validate(mc, A='a')

		# clear move with one kind
		mc.clear_all('a')
		self.validate(mc)

		# "clear" move with no kinds
		mc.clear_all('c')
		self.validate(mc)

def flat(it):
	for x in it:
		yield from x
