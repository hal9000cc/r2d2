"""
Tests for Objects2Redis and Objects2RedisList classes.
"""
import pytest
from typing import Type
from pydantic import Field
from app.core.objects2redis import Objects2Redis, Objects2RedisList


# Test classes
class SampleObject(Objects2Redis):
    """Sample object class for testing Objects2Redis"""
    
    name: str = ""
    value: int = 0
    category: str = ""
    
    def get_key(self) -> str:
        """Returns key as 'category:name'"""
        if self.category and self.name:
            return f"{self.category}:{self.name}"
        return ""


class SampleObjectList(Objects2RedisList[SampleObject]):
    """Sample list class for testing Objects2RedisList"""
    
    def list_key(self) -> str:
        return "test_objects"
    
    def object_class(self) -> Type[SampleObject]:
        return SampleObject


# Fixtures
@pytest.fixture
def redis_params():
    """Redis connection parameters for testing"""
    return {
        'host': 'localhost',
        'port': 6379,
        'db': 0,
        'password': None
    }


@pytest.fixture
def test_list(redis_params):
    """Create SampleObjectList instance"""
    obj_list = SampleObjectList(redis_params)
    
    # Clean up any existing test data
    client = obj_list._get_redis_client()
    pattern = f"{obj_list.list_key()}:*"
    keys = client.keys(pattern)
    if keys:
        client.delete(*keys)
    
    yield obj_list
    
    # Clean up after test
    keys = client.keys(pattern)
    if keys:
        client.delete(*keys)


# Tests
class TestObjects2Redis:
    """Tests for Objects2Redis base class"""
    
    def test_create_object(self):
        """Test creating object with fields"""
        obj = SampleObject(id=1, name="test", value=100, category="cat1")
        assert obj.id == 1
        assert obj.name == "test"
        assert obj.value == 100
        assert obj.category == "cat1"
    
    def test_get_key(self):
        """Test get_key method"""
        obj = SampleObject(id=1, name="apple", value=10, category="fruit")
        assert obj.get_key() == "fruit:apple"
        
        obj2 = SampleObject(id=2, name="", value=20, category="")
        assert obj2.get_key() == ""
    
    def test_pydantic_validation(self):
        """Test Pydantic validation"""
        # Valid data
        obj = SampleObject(id=1, name="test", value=100)
        assert isinstance(obj, SampleObject)
        
        # Invalid type should raise validation error
        with pytest.raises(Exception):
            SampleObject(id="invalid", name="test")
    
    def test_model_dump(self):
        """Test serialization via model_dump"""
        obj = SampleObject(id=1, name="test", value=100, category="cat1")
        data = obj.model_dump()
        
        assert data == {
            'id': 1,
            'name': 'test',
            'value': 100,
            'category': 'cat1'
        }
        # _list should be excluded
        assert '_list' not in data
    
    def test_model_validate(self):
        """Test deserialization via model_validate"""
        data = {'id': 1, 'name': 'test', 'value': 100, 'category': 'cat1'}
        obj = SampleObject.model_validate(data)
        
        assert obj.id == 1
        assert obj.name == "test"
        assert obj.value == 100
        assert obj.category == "cat1"


class TestObjects2RedisList:
    """Tests for Objects2RedisList base class"""
    
    def test_startup_shutdown(self, test_list):
        """Test startup and shutdown methods"""
        # Should not raise any errors
        test_list.startup()
        test_list.shutdown()
    
    def test_new_object(self, test_list):
        """Test creating new object with unique id"""
        obj1 = test_list.new()
        assert obj1.id == 1
        assert obj1._list == test_list
        
        obj2 = test_list.new()
        assert obj2.id == 2
        assert obj2._list == test_list
        
        # IDs should be unique
        assert obj1.id != obj2.id
    
    def test_save_and_load(self, test_list):
        """Test saving and loading object"""
        # Create and save object
        obj = test_list.new()
        obj.name = "apple"
        obj.value = 100
        obj.category = "fruit"
        obj.save()
        
        # Load object
        loaded = test_list.load(obj.id)
        assert loaded is not None
        assert loaded.id == obj.id
        assert loaded.name == "apple"
        assert loaded.value == 100
        assert loaded.category == "fruit"
        assert loaded._list == test_list
    
    def test_load_nonexistent(self, test_list):
        """Test loading non-existent object"""
        loaded = test_list.load(9999)
        assert loaded is None
    
    def test_save_update(self, test_list):
        """Test updating existing object"""
        # Create and save
        obj = test_list.new()
        obj.name = "apple"
        obj.value = 100
        obj.category = "fruit"
        obj.save()
        
        # Update and save again
        obj.value = 200
        obj.save()
        
        # Load and verify update
        loaded = test_list.load(obj.id)
        assert loaded.value == 200
    
    def test_list_objects(self, test_list):
        """Test listing all objects"""
        # Create several objects
        obj1 = test_list.new()
        obj1.name = "apple"
        obj1.category = "fruit"
        obj1.save()
        
        obj2 = test_list.new()
        obj2.name = "banana"
        obj2.category = "fruit"
        obj2.save()
        
        obj3 = test_list.new()
        obj3.name = "carrot"
        obj3.category = "vegetable"
        obj3.save()
        
        # List all objects
        objects = test_list.list()
        assert len(objects) == 3
        
        # Check that all objects are present
        names = {obj.name for obj in objects}
        assert names == {"apple", "banana", "carrot"}
        
        # Check that _list is set
        for obj in objects:
            assert obj._list == test_list
    
    def test_delete_object(self, test_list):
        """Test deleting object"""
        # Create and save
        obj = test_list.new()
        obj.name = "apple"
        obj.category = "fruit"
        obj.save()
        
        obj_id = obj.id
        
        # Verify exists
        assert test_list.load(obj_id) is not None
        
        # Delete
        test_list.delete(obj_id)
        
        # Verify deleted
        assert test_list.load(obj_id) is None
    
    def test_delete_nonexistent(self, test_list):
        """Test deleting non-existent object raises KeyError"""
        with pytest.raises(KeyError):
            test_list.delete(9999)
    
    def test_load_by_key(self, test_list):
        """Test loading object by secondary key"""
        # Create and save
        obj = test_list.new()
        obj.name = "apple"
        obj.value = 100
        obj.category = "fruit"
        obj.save()
        
        # Load by key
        loaded = test_list.load_by_key("fruit:apple")
        assert loaded is not None
        assert loaded.id == obj.id
        assert loaded.name == "apple"
        assert loaded.value == 100
    
    def test_load_by_key_nonexistent(self, test_list):
        """Test loading by non-existent key"""
        loaded = test_list.load_by_key("nonexistent:key")
        assert loaded is None
    
    def test_key_uniqueness(self, test_list):
        """Test that duplicate keys raise ValueError"""
        # Create first object
        obj1 = test_list.new()
        obj1.name = "apple"
        obj1.category = "fruit"
        obj1.save()
        
        # Try to create second object with same key
        obj2 = test_list.new()
        obj2.name = "apple"
        obj2.category = "fruit"
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="already exists"):
            obj2.save()
    
    def test_key_change(self, test_list):
        """Test changing object key"""
        # Create and save
        obj = test_list.new()
        obj.name = "apple"
        obj.category = "fruit"
        obj.save()
        
        # Verify can load by old key
        assert test_list.load_by_key("fruit:apple") is not None
        
        # Change key
        obj.name = "orange"
        obj.save()
        
        # Old key should not work
        assert test_list.load_by_key("fruit:apple") is None
        
        # New key should work
        loaded = test_list.load_by_key("fruit:orange")
        assert loaded is not None
        assert loaded.id == obj.id
        assert loaded.name == "orange"
    
    def test_key_change_with_conflict(self, test_list):
        """Test changing key to existing key raises ValueError"""
        # Create two objects
        obj1 = test_list.new()
        obj1.name = "apple"
        obj1.category = "fruit"
        obj1.save()
        
        obj2 = test_list.new()
        obj2.name = "banana"
        obj2.category = "fruit"
        obj2.save()
        
        # Try to change obj2 key to conflict with obj1
        obj2.name = "apple"
        
        with pytest.raises(ValueError, match="already exists"):
            obj2.save()
    
    def test_delete_with_index(self, test_list):
        """Test that delete removes both object and index"""
        # Create and save
        obj = test_list.new()
        obj.name = "apple"
        obj.category = "fruit"
        obj.save()
        
        obj_id = obj.id
        key = obj.get_key()
        
        # Verify index exists
        assert test_list.load_by_key(key) is not None
        
        # Delete
        test_list.delete(obj_id)
        
        # Verify both object and index are deleted
        assert test_list.load(obj_id) is None
        assert test_list.load_by_key(key) is None
    
    def test_empty_key(self, test_list):
        """Test saving object with empty key"""
        # Create object without key
        obj = test_list.new()
        obj.name = ""
        obj.category = ""
        obj.value = 100
        obj.save()
        
        # Should be able to load by id
        loaded = test_list.load(obj.id)
        assert loaded is not None
        assert loaded.value == 100
    
    def test_redis_key_format(self, test_list):
        """Test Redis key format"""
        obj = test_list.new()
        obj.save()
        
        # Check object key format
        obj_key = test_list._get_object_key(obj.id)
        assert obj_key == f"test_objects:obj:{obj.id}"
        
        # Check index key format
        obj.name = "apple"
        obj.category = "fruit"
        obj.save()
        
        index_key = test_list._get_index_key("fruit:apple")
        assert index_key == "test_objects:index:fruit:apple"
    
    def test_concurrent_operations(self, test_list):
        """Test that operations maintain consistency"""
        # Create multiple objects
        objects = []
        for i in range(10):
            obj = test_list.new()
            obj.name = f"item{i}"
            obj.category = "test"
            obj.value = i * 10
            obj.save()
            objects.append(obj)
        
        # Verify all can be loaded
        loaded_objects = test_list.list()
        assert len(loaded_objects) == 10
        
        # Verify all keys work
        for obj in objects:
            loaded = test_list.load_by_key(f"test:item{objects.index(obj)}")
            assert loaded is not None
        
        # Delete some
        for i in [0, 2, 5, 7]:
            test_list.delete(objects[i].id)
        
        # Verify correct count
        remaining = test_list.list()
        assert len(remaining) == 6

