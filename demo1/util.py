import logging
from termcolor import colored

# FIXME color in here is a total hack

class debug():
	def __init__(self, prefix='', member=False):
		self.prefix = prefix
		self.is_member = member

	def __call__(self, func):
		from functools import wraps
		@wraps(func)
		def wrapped(*args, **kw):
			args2show = args[1 if self.is_member else 0:]
			logging.debug(
				colored(self.prefix, 'green') +
				format_func_call(colored(func.__name__, 'yellow'), args2show, kw))
			return func(*args, **kw)
		return wrapped

def format_func_call(name, args, kw):
	argstrs = [repr(x) for x in args]
	kwstrs = ['{!s}={!r}'.format(k,v) for (k,v) in kw.items()]

	pat = '{}%s{}%s' % (colored('(', 'yellow'), colored(')', 'yellow'))
	sep = colored(', ', 'yellow')
	return pat.format(name, (sep.join(argstrs + kwstrs)))

