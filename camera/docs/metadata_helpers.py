#
# Copyright (C) 2012 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
A set of helpers for rendering Mako templates with a Metadata model.
"""

import metadata_model
import re
from collections import OrderedDict

_context_buf = None

def _is_sec_or_ins(x):
  return isinstance(x, metadata_model.Section) or    \
         isinstance(x, metadata_model.InnerNamespace)

##
## Metadata Helpers
##

def find_all_sections(root):
  """
  Find all descendants that are Section or InnerNamespace instances.

  Args:
    root: a Metadata instance

  Returns:
    A list of Section/InnerNamespace instances

  Remarks:
    These are known as "sections" in the generated C code.
  """
  return root.find_all(_is_sec_or_ins)

def find_parent_section(entry):
  """
  Find the closest ancestor that is either a Section or InnerNamespace.

  Args:
    entry: an Entry or Clone node

  Returns:
    An instance of Section or InnerNamespace
  """
  return entry.find_parent_first(_is_sec_or_ins)

# find uniquely named entries (w/o recursing through inner namespaces)
def find_unique_entries(node):
  """
  Find all uniquely named entries, without recursing through inner namespaces.

  Args:
    node: a Section or InnerNamespace instance

  Yields:
    A sequence of MergedEntry nodes representing an entry

  Remarks:
    This collapses multiple entries with the same fully qualified name into
    one entry (e.g. if there are multiple entries in different kinds).
  """
  if not isinstance(node, metadata_model.Section) and    \
     not isinstance(node, metadata_model.InnerNamespace):
      raise TypeError("expected node to be a Section or InnerNamespace")

  d = OrderedDict()
  # remove the 'kinds' from the path between sec and the closest entries
  # then search the immediate children of the search path
  search_path = isinstance(node, metadata_model.Section) and node.kinds \
                or [node]
  for i in search_path:
      for entry in i.entries:
          d[entry.name] = entry

  for k,v in d.iteritems():
      yield v.merge()

def path_name(node):
  """
  Calculate a period-separated string path from the root to this element,
  by joining the names of each node and excluding the Metadata/Kind nodes
  from the path.

  Args:
    node: a Node instance

  Returns:
    A string path
  """

  isa = lambda x,y: isinstance(x, y)
  fltr = lambda x: not isa(x, metadata_model.Metadata) and \
                   not isa(x, metadata_model.Kind)

  path = node.find_parents(fltr)
  path = list(path)
  path.reverse()
  path.append(node)

  return ".".join((i.name for i in path))

def has_descendants_with_enums(node):
  """
  Determine whether or not the current node is or has any descendants with an
  Enum node.

  Args:
    node: a Node instance

  Returns:
    True if it finds an Enum node in the subtree, False otherwise
  """
  return bool(node.find_first(lambda x: isinstance(x, metadata_model.Enum)))

def get_children_by_throwing_away_kind(node, member='entries'):
  """
  Get the children of this node by compressing the subtree together by removing
  the kind and then combining any children nodes with the same name together.

  Args:
    node: An instance of Section, InnerNamespace, or Kind

  Returns:
    An iterable over the combined children of the subtree of node,
    as if the Kinds never existed.

  Remarks:
    Not recursive. Call this function repeatedly on each child.
  """

  if isinstance(node, metadata_model.Section):
    # Note that this makes jump from Section to Kind,
    # skipping the Kind entirely in the tree.
    node_to_combine = node.combine_kinds_into_single_node()
  else:
    node_to_combine = node

  combined_kind = node_to_combine.combine_children_by_name()

  return (i for i in getattr(combined_kind, member))

def get_children_by_filtering_kind(section, kind_name, member='entries'):
  """
  Takes a section and yields the children of the kind under this section.

  Args:
    section: An instance of Section
    kind_name: A name of the kind, i.e. 'dynamic' or 'static' or 'controls'

  Returns:
    An iterable over the children of the specified kind.
  """

# TODO: test/use this function
  matched_kind = next((i for i in section.kinds if i.name == kind_name), None)

  if matched_kind:
    return getattr(matched_kind, member)
  else:
    return ()

##
## Filters
##

# abcDef.xyz -> ABC_DEF_XYZ
def csym(name):
  """
  Convert an entry name string into an uppercase C symbol.

  Returns:
    A string

  Example:
    csym('abcDef.xyz') == 'ABC_DEF_XYZ'
  """
  newstr = name
  newstr = "".join([i.isupper() and ("_" + i) or i for i in newstr]).upper()
  newstr = newstr.replace(".", "_")
  return newstr

# abcDef.xyz -> abc_def_xyz
def csyml(name):
  """
  Convert an entry name string into a lowercase C symbol.

  Returns:
    A string

  Example:
    csyml('abcDef.xyz') == 'abc_def_xyz'
  """
  return csym(name).lower()

# pad with spaces to make string len == size. add new line if too big
def ljust(size, indent=4):
  """
  Creates a function that given a string will pad it with spaces to make
  the string length == size. Adds a new line if the string was too big.

  Args:
    size: an integer representing how much spacing should be added
    indent: an integer representing the initial indendation level

  Returns:
    A function that takes a string and returns a string.

  Example:
    ljust(8)("hello") == 'hello   '

  Remarks:
    Deprecated. Use pad instead since it works for non-first items in a
    Mako template.
  """
  def inner(what):
    newstr = what.ljust(size)
    if len(newstr) > size:
      return what + "\n" + "".ljust(indent + size)
    else:
      return newstr
  return inner

def _find_new_line():

  if _context_buf is None:
    raise ValueError("Context buffer was not set")

  buf = _context_buf
  x = -1 # since the first read is always ''
  cur_pos = buf.tell()
  while buf.tell() > 0 and buf.read(1) != '\n':
    buf.seek(cur_pos - x)
    x = x + 1

  buf.seek(cur_pos)

  return int(x)

# Pad the string until the buffer reaches the desired column.
# If string is too long, insert a new line with 'col' spaces instead
def pad(col):
  """
  Create a function that given a string will pad it to the specified column col.
  If the string overflows the column, put the string on a new line and pad it.

  Args:
    col: an integer specifying the column number

  Returns:
    A function that given a string will produce a padded string.

  Example:
    pad(8)("hello") == 'hello   '

  Remarks:
    This keeps track of the line written by Mako so far, so it will always
    align to the column number correctly.
  """
  def inner(what):
    wut = int(col)
    current_col = _find_new_line()

    if len(what) > wut - current_col:
      return what + "\n".ljust(col)
    else:
      return what.ljust(wut - current_col)
  return inner

# int32 -> TYPE_INT32, byte -> TYPE_BYTE, etc. note that enum -> TYPE_INT32
def ctype_enum(what):
  """
  Generate a camera_metadata_type_t symbol from a type string.

  Args:
    what: a type string

  Returns:
    A string representing the camera_metadata_type_t

  Example:
    ctype_enum('int32') == 'TYPE_INT32'
    ctype_enum('int64') == 'TYPE_INT64'
    ctype_enum('float') == 'TYPE_FLOAT'

  Remarks:
    An enum is coerced to a byte since the rest of the camera_metadata
    code doesn't support enums directly yet.
  """
  return 'TYPE_%s' %(what.upper())

def jtype(entry):
  """
  Calculate the Java type from an entry type string, to be used as a generic
  type argument in Java. The type is guaranteed to inherit from Object.

  Remarks:
    Since Java generics cannot be instantiated with primitives, this version
    will use boxed types when absolutely required.

  Returns:
    The string representing the Java type.
  """

  if not isinstance(entry, metadata_model.Entry):
    raise ValueError("Expected entry to be an instance of Entry")

  primitive_type = entry.type

  if entry.enum:
    name = entry.name

    name_without_ons = entry.get_name_as_list()[1:]
    base_type = ".".join([pascal_case(i) for i in name_without_ons]) + \
                 "Key.Enum"
  else:
    mapping = {
      'int32': 'Integer',
      'int64': 'Long',
      'float': 'Float',
      'double': 'Double',
      'byte': 'Byte',
      'rational': 'Rational'
    }

    base_type = mapping[primitive_type]

  if entry.container == 'array':
    additional = '[]'

    #unbox if it makes sense
    if primitive_type != 'rational' and not entry.enum:
      base_type = jtype_primitive(primitive_type)
  else:
    additional = ''

  return "%s%s" %(base_type, additional)

def jtype_primitive(what):
  """
  Calculate the Java type from an entry type string.

  Remarks:
    Makes a special exception for Rational, since it's a primitive in terms of
    the C-library camera_metadata type system.

  Returns:
    The string representing the primitive type
  """
  mapping = {
    'int32': 'int',
    'int64': 'long',
    'float': 'float',
    'double': 'double',
    'byte': 'byte',
    'rational': 'Rational'
  }

  try:
    return mapping[what]
  except KeyError as e:
    raise ValueError("Can't map '%s' to a primitive, not supported" %what)

def jclass(entry):
  """
  Calculate the java Class reference string for an entry.

  Args:
    entry: an Entry node

  Example:
    <entry name="some_int" type="int32"/>
    <entry name="some_int_array" type="int32" container='array'/>

    jclass(some_int) == 'int.class'
    jclass(some_int_array) == 'int[].class'

  Returns:
    The ClassName.class string
  """
  the_type = entry.type
  try:
    class_name = jtype_primitive(the_type)
  except ValueError as e:
    class_name = the_type

  if entry.container == 'array':
    class_name += "[]"

  return "%s.class" %class_name

def jidentifier(what):
  """
  Convert the input string into a valid Java identifier.

  Args:
    what: any identifier string

  Returns:
    String with added underscores if necessary.
  """
  if re.match("\d", what):
    return "_%s" %what
  else:
    return what

def enum_calculate_value_string(enum_value):
  """
  Calculate the value of the enum, even if it does not have one explicitly
  defined.

  This looks back for the first enum value that has a predefined value and then
  applies addition until we get the right value, using C-enum semantics.

  Args:
    enum_value: an EnumValue node with a valid Enum parent

  Example:
    <enum>
      <value>X</value>
      <value id="5">Y</value>
      <value>Z</value>
    </enum>

    enum_calculate_value_string(X) == '0'
    enum_calculate_Value_string(Y) == '5'
    enum_calculate_value_string(Z) == '6'

  Returns:
    String that represents the enum value as an integer literal.
  """

  enum_value_siblings = list(enum_value.parent.values)
  this_index = enum_value_siblings.index(enum_value)

  def is_hex_string(instr):
    return bool(re.match('0x[a-f0-9]+$', instr, re.IGNORECASE))

  base_value = 0
  base_offset = 0
  emit_as_hex = False

  this_id = enum_value_siblings[this_index].id
  while this_index != 0 and not this_id:
    this_index -= 1
    base_offset += 1
    this_id = enum_value_siblings[this_index].id

  if this_id:
    base_value = int(this_id, 0)  # guess base
    emit_as_hex = is_hex_string(this_id)

  if emit_as_hex:
    return "0x%X" %(base_value + base_offset)
  else:
    return "%d" %(base_value + base_offset)

def enumerate_with_last(iterable):
  """
  Enumerate a sequence of iterable, while knowing if this element is the last in
  the sequence or not.

  Args:
    iterable: an Iterable of some sequence

  Yields:
    (element, bool) where the bool is True iff the element is last in the seq.
  """
  it = (i for i in iterable)

  first = next(it)  # OK: raises exception if it is empty

  second = first  # for when we have only 1 element in iterable

  try:
    while True:
      second = next(it)
      # more elements remaining.
      yield (first, False)
      first = second
  except StopIteration:
    # last element. no more elements left
    yield (second, True)

def pascal_case(what):
  """
  Convert the first letter of a string to uppercase, to make the identifier
  conform to PascalCase.

  Args:
    what: a string representing some identifier

  Returns:
    String with first letter capitalized

  Example:
    pascal_case("helloWorld") == "HelloWorld"
    pascal_case("foo") == "Foo"
  """
  return what[0:1].upper() + what[1:]

def jenum(enum):
  """
  Calculate the Java symbol referencing an enum value (in Java).

  Args:
    enum: An Enum node

  Returns:
    String representing the Java symbol
  """

  entry = enum.parent
  name = entry.name

  name_without_ons = entry.get_name_as_list()[1:]
  jenum_name = ".".join([pascal_case(i) for i in name_without_ons]) + "Key.Enum"

  return jenum_name

