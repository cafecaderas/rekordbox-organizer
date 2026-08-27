import pytest

from app.taxonomy_store import TaxonomyError, TaxonomyStore


def _store(tmp_path):
    return TaxonomyStore(tmp_path / "taxonomy.json")


def test_create_top_level_and_child(tmp_path):
    store = _store(tmp_path)
    afro = store.create("Afro House")
    deep = store.create("Afro Deep", parent_id=afro.id)
    assert deep.parent_id == afro.id
    assert store.path_name(deep.id) == "Afro House > Afro Deep"


def test_create_blank_name_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(TaxonomyError):
        store.create("   ")


def test_create_under_unknown_parent_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(TaxonomyError):
        store.create("X", parent_id="does-not-exist")


def test_rename(tmp_path):
    store = _store(tmp_path)
    node = store.create("Afro House")
    store.rename(node.id, "Afro House (Personal)")
    assert store.get(node.id).name == "Afro House (Personal)"


def test_move_reparents_node(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    b = store.create("B")
    child = store.create("Child", parent_id=a.id)
    store.move(child.id, b.id)
    assert store.get(child.id).parent_id == b.id


def test_move_under_self_raises(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    with pytest.raises(TaxonomyError):
        store.move(a.id, a.id)


def test_move_under_own_descendant_raises(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    b = store.create("B", parent_id=a.id)
    c = store.create("C", parent_id=b.id)
    with pytest.raises(TaxonomyError):
        store.move(a.id, c.id)


def test_merge_reparents_children_and_removes_source(tmp_path):
    store = _store(tmp_path)
    source = store.create("Melodic")
    target = store.create("Melodic House")
    child = store.create("Melodic Deep", parent_id=source.id)

    store.merge(source.id, target.id)

    assert store.get(source.id) is None
    assert store.get(child.id).parent_id == target.id


def test_merge_self_raises(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    with pytest.raises(TaxonomyError):
        store.merge(a.id, a.id)


def test_merge_into_own_descendant_raises(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    b = store.create("B", parent_id=a.id)
    with pytest.raises(TaxonomyError):
        store.merge(a.id, b.id)


def test_delete_leaf_succeeds_without_cascade(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    removed = store.delete(a.id)
    assert removed == [a.id]
    assert store.get(a.id) is None


def test_delete_node_with_children_requires_cascade(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    store.create("Child", parent_id=a.id)
    with pytest.raises(TaxonomyError):
        store.delete(a.id)


def test_delete_with_cascade_removes_subtree(tmp_path):
    store = _store(tmp_path)
    a = store.create("A")
    b = store.create("B", parent_id=a.id)
    c = store.create("C", parent_id=b.id)
    removed = store.delete(a.id, cascade=True)
    assert set(removed) == {a.id, b.id, c.id}
    assert store.get(a.id) is None
    assert store.get(b.id) is None
    assert store.get(c.id) is None


def test_tree_nests_children_under_parents(tmp_path):
    store = _store(tmp_path)
    afro = store.create("Afro House")
    store.create("Afro Deep", parent_id=afro.id)
    store.create("Afro Peak", parent_id=afro.id)
    store.create("Techno")

    tree = store.tree()
    names = {n["name"] for n in tree}
    assert names == {"Afro House", "Techno"}
    afro_node = next(n for n in tree if n["name"] == "Afro House")
    assert {c["name"] for c in afro_node["children"]} == {"Afro Deep", "Afro Peak"}


def test_flat_list_includes_full_paths(tmp_path):
    store = _store(tmp_path)
    afro = store.create("Afro House")
    store.create("Afro Deep", parent_id=afro.id)
    paths = {row["path"] for row in store.flat_list()}
    assert paths == {"Afro House", "Afro House > Afro Deep"}


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "taxonomy.json"
    store1 = TaxonomyStore(path)
    afro = store1.create("Afro House")
    store1.create("Afro Deep", parent_id=afro.id)

    store2 = TaxonomyStore(path)
    assert {row["path"] for row in store2.flat_list()} == {"Afro House", "Afro House > Afro Deep"}


def test_no_file_written_until_first_mutation(tmp_path):
    path = tmp_path / "taxonomy.json"
    TaxonomyStore(path)
    assert not path.exists()
    store = TaxonomyStore(path)
    store.create("A")
    assert path.exists()
