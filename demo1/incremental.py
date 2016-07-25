import random
import sys
import numpy as np
from collections import defaultdict, Counter

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
		print(list(self.__kindset))
		print('ADD', move, file=sys.stderr)
		kindset = self.__kindset.pop(move, frozenset())
		if kind in kindset:
			raise ValueError("kind already present")
		kindset |= set([kind])
		self.__kindset[move] = kindset

	def clear_one(self, move, kind):
		kindset = self.__kindset.pop(move)
		if kind not in kindset:
			raise ValueError("kind not present")
		kindset -= set([kind])
		if kindset:
			self.__kindset[move] = kindset

	def clear_all(self, move):
		print('CLEAR_ALL', move, file=sys.stderr)
		self.__kindset.pop(move, frozenset())

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

		Each move is only counted once across all counts.
		A Move associated with multiple Kinds will be counted under a key with the
		frozenset of those kinds.
		'''
		return self.__kindset.value_counts()


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
		self.__keys = defaultdict(list) # {value: [keys]}

		# behave like dict constructor
		if args and isinstance(args[0], ReverseDict):
			args[0] = args[0].items()
		for (k,v) in dict(*args, **kw).items():
			self.__setitem__(k, v)

	def lookup_keys(self, value):
		''' Iterate through all keys for a value. '''
		return self.__keys[value].__iter__()

	# common methods for containers
	def __len__(self): return self.__value.__len__()
	def __iter__(self): return self.__value.__iter__()
	def __contains__(self, key): return self.__value.__contains__(key)
	def __nonzero__(self): return self.__value.__nonzero__()

	# operators
	def __eq__(self, other): return self.__value.__eq__(other.__value)

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

	def debug_validate(self, correct):
		''' For debug.  Only use inside an ``assert`` statement. '''
		# compare to a gold standard
		assert self.__value == correct.__value
		assert self.__keys == correct.__keys

		# check integrity of index lookup
		for (value,keys) in self.__keys.items():
			for (idx,key) in enumerate(keys):
				assert self.__index[(key,value)] == idx

		return True

	def pop_arbitrary_key(self, value):
		''' O(1) retrieval and removal of an arbitrarily chosen key for a given value. '''
		key = self.__keys[value][0]
		self.__remove_key(key)
		return key

	def pop_random_key(self, value, rng=random):
		''' O(1) retrieval and removal of a randomly chosen key for a given value. '''
		key = self.get_random_key(value, rng)
		self.__remove_key(key)
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

