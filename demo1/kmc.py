import random
import bisect
import operator
from .util import partial_sums

__all__ = ['weighted_choice']

# NOTE: pretty much this whole file could be replaced with
#  something along the lines of:
#
#    values,weights = zip(*choices)
#    weights = np.array(weights)/math.fsum(weights)
#    values = turn_list_of_tuples_into_1d_array_of_object_by_some_obscene_hack(values)
#    return np.random.choice(values, p=weights)
#
# Though this would ever-so-slightly impact the probability
# distribution in an unclear manner. (also, it would require
# aforementioned "obscene hack")

# weighted_choice :: [(value, weight)] -> value
def weighted_choice(choices, howmany=None, rng=random):
	'''
	A weighted random choice.

	The weights do not need to add to 1.
	'''

	# Filter out zeros to unify some edge cases
	# (namely, an empty list versus a nonempty list of zero weights)
	choices = [(v,w) for (v,w) in choices if w != 0.]
	if not choices:
		raise ValueError("Cannot choose from total weight of zero!")

	# Sort by weight to avoid precision loss in cumulative weights
	choices = sorted(choices, key=operator.itemgetter(1))
	values, weights = zip(*choices)
	if weights[0] < 0.:
		w,v = weights[0], values[0]
		raise ValueError("Negative weight {!s} for {!r}".format(w,v))

	cumul_weights = list(partial_sums(weights, with_zero=False))
	total_weight = cumul_weights[-1]
	assert len(cumul_weights) == len(values)
	assert total_weight > 0. # already handled

	bisect_left = bisect.bisect_left
	uniform = rng.uniform
	def do_eet():
		x = uniform(0., total_weight)
		i = bisect_left(cumul_weights, x)
		return values[i]

	if howmany is None: return do_eet()
	else: return [do_eet() for _ in range(howmany)]
