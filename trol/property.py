import pickle
from trol import RedisKeyError, Serializer, Deserializer


class Property(object):
    """A property object which emulates a remote object as local

    The expectation is that this Property object is embedded as a class level attribute
    The class it is embedded in should define `redis` and `key` attrbutes to define where this property is stored

    Note:
        This class is intended to be used with trol.Model subclasses, but can work on it's own

    Args:
        autocommit (bool): Commit the local value to Redis on every assignment
            If set to None, assignments will check the holder object for an autocommit value, and default to True if not present
            Useful if you don't want to worry about forgetting to commit
        alwaysfetch (bool): Fetch the latest value from the database
            If set to None, gets will check the holder object for an alwaysfetch value, and default to True if not present
            Useful if you have multiple threads or processes frequently modifying the database
        serializer (Callable[[object], bytes]): A function or callable which will be used for serializing the value before storage in Redis
            Although bytes is the most general output type, this function may also output `str`, `int`, or any other type redis=py will accept
            Default is `pickle.dumps`, which is not human readable, but will work with most python object
        deserializer (Callable[[bytes], object]): A function or callable which will be used for deserializing the value after reciving it from redis
            Default is `pickle.loads`, the counterpart for the deafault serializer

    Args:
        autocommit (bool): Sets the autocommit attribute. Defaults to None
        alwayfetch (bool): Sets the alwaysfetch attribute. Defaults to None
        serializer (Callable[[object], bytes]): Sets the serializer attribute. Defaults to None
        deserializer (Callable[[bytes], object]): Sets the deserializer attribute. Defaults to None
    """
    class Null:
        """A class to act as an indicator value"""

    null = Null()
    """Property.Null: An indicator field to show the value needs to be fetched"""

    @staticmethod
    def mangle(name):
        """Creates a mangled version of the inputted name

        Mangling is the process of changing an attribute name in such a way that it will liekly not collide with other attributes

        Args:
            name (str): The name which should be mangled

        Returns:
            str: The mangled name
        """
        return "_trol_property_{}".format(name)

    def __init__(self, name=None, typ=None, autocommit=None, alwaysfetch=None, serializer=None, deserializer=None):
        self.name = name
        self.autocommit = autocommit
        self.alwaysfetch = alwaysfetch

        self._typ = typ
        if serializer is None:
            if typ is None:
                self.serialize = pickle.dumps
            else:
                self.serialize = Serializer(typ)
        else:
            self.serialize = serializer

        if deserializer is None:
            if typ is None:
                self.deserialize = pickle.loads
            else:
                self.deserialize = Deserializer(typ)
        else:
            self.deserialize = deserializer

    def __get__(self, obj, typ=None):
        if obj is None:
            return self

        value = self.value(obj)

        if value is self.null or self.alwaysfetch or (self.alwaysfetch is None and getattr(obj, 'alwaysfetch', False)):
            value = self.fetch(obj)

        if value is self.null:
            raise RedisKeyError(self.key(obj))

        return value

    def __set__(self, obj, value):
        self.set(obj, value)

        if self.autocommit or (self.autocommit is None and getattr(obj, 'autocommit', True)):
            self.commit(obj)

    @property
    def name(self):
        """``str``: The name for this property, which will be used to determine the key when bound to a Model"""
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    def fetch(self, obj):
        """Retrieves and sets the value of this property

        Args:
            obj (object): This property's holder

        Returns:
            bytes: The data retrieved or None in the case of a key not found
        """
        response = obj.redis.get(self.key(obj))

        if response is not None:
            value = self.deserialize(response)
        else:
            value = self.null

        self.set(obj, value)
        return value

    def commit(self, obj):
        """Commits this properties value to Redis

        Does nothing if the value is Property.null, which means there is nothing to write

        Args:
            obj (object): This property's holder

        Returns:
            bool: True if the set transaction was successful. False otherwise
        """
        value = self.value(obj)
        if self.value(obj) is self.null:
            return True

        return obj.redis.set(self.key(obj), self.serialize(value))

    def delete(self, obj):
        """Deletes the key of this property from Redis

        Args:
            obj (object): This property's holder

        Returns:
            bool: True if the delete transaction was successful. False otherwise
        """
        ok = obj.redis.delete(self.key(obj))
        if ok:
            self.set(obj, None)
        return ok

    def exists(self, obj):
        """Checks whether or not a value is set for this property in Redis

        Args:
            obj (object): This property's holder

        Returns:
            bool: True if the key have a value in Redis. False otherwise
        """
        return obj.redis.exists(self.key(obj))

    def invalidate(self, obj):
        """Invalidates the local value to indicate a fetch must be done

        Args:
            obj (object): This property's holder
        """
        self.set(obj, self.null)

    def key(self, obj):
        """Gets the key where this property's data exists  in Redis

        The key for this property is the key of it's holder, with `:<name>` appended

        Args:
            obj (object): This propery's holder

        Returns:
            str: The key which can be used to get this property's data from Redis
        """
        if obj.key is not None:
            return "{}:{}".format(obj.key, self.name)
        else:
            return self.name

    def value(self, obj):
        """Gets the value stored in the holder obj

        Sets the property value attribute in the holder if it does not already exist

        Args:
            obj (object): This propery's holder

        Returns:
            object: The local value of this property
        """
        try:
            value = getattr(obj, self.mangle(self.name))
        except AttributeError:
            self.set(obj, self.null)
            value = self.null
        return value

    def set(self, obj, value):
        """Sets the value stored in the holder obj

        Args:
            obj (object): This propery's holder
            value (object): The value to set
        """
        setattr(obj, self.mangle(self.name), value)
