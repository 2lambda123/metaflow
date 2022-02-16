from metaflow.datastore import DATASTORES, FlowDataStore
from metaflow.metaflow_config import DATASTORE_CARD_SUFFIX
from .card_resolver import resolve_paths_from_task, resumed_info
from .card_datastore import CardDatastore
from .exception import (
    UnresolvableDatastoreException,
    IncorrectArguementException,
    IncorrectPathspecException,
)
import os
import tempfile
import uuid

_TYPE = type
_ID_FUNC = id


class Card:
    """
    The object which holds the html of a Metaflow card.

    ### Usage
    ```python
    card_container = get_cards(task)
    # This retrieves a `Card` instance
    card = card_container[0]
    # View the HTML in browser
    card.view()
    # Get the HTML of the card
    html = card.get()
    # calling the instance of `Card` inside a notebook cell will render the card as the output of a cell
    card
    ```
    """

    def __init__(
        self,
        card_ds,
        type,
        path,
        hash,
        id=None,
        html=None,
        created_on=None,
        from_resumed=False,
        origin_pathspec=None,
    ):
        # private attributes
        self._path = path
        self._html = html
        self._created_on = created_on
        self._card_ds = card_ds
        self._card_id = id

        # public attributes
        self.hash = hash
        self.type = type
        self.from_resumed = from_resumed
        self.origin_pathspec = origin_pathspec

        # Tempfile to open stuff in browser
        self._temp_file = None

    def get(self):
        if self._html is not None:
            return self._html
        self._html = self._card_ds.get_card_html(self.path)
        return self._html

    @property
    def path(self):
        return self._path

    @property
    def id(self):
        return self._card_id

    def __str__(self):
        return "<Card at '%s'>" % self._path

    def view(self):
        import webbrowser

        self._temp_file = tempfile.NamedTemporaryFile(suffix=".html")
        html = self.get()
        self._temp_file.write(html.encode())
        self._temp_file.seek(0)
        url = "file://" + os.path.abspath(self._temp_file.name)
        webbrowser.open(url)

    def _repr_html_(self):
        main_html = []
        container_id = uuid.uuid4()
        main_html.append(
            "<script type='text/javascript'>var mfContainerId = '%s';</script>"
            % container_id
        )
        main_html.append(
            "<div class='embed' data-container='%s'>%s</div>"
            % (container_id, self.get())
        )
        return "\n".join(main_html)


class CardContainer:
    """
    A `list` like object that helps iterate through all the stored `Card`s.

    ### Usage:
    ```python
    card_container = get_cards(task)
    # Get all stored cards
    cards = list(card_container)
    # calling the instance of `CardContainer` inside a notebook will render all cards as the output of a cell
    card_container
    ```
    """

    def __init__(self, card_paths, card_ds, from_resumed=False, origin_pathspec=None):
        self._card_paths = card_paths
        self._card_ds = card_ds
        self._current = 0
        self._high = len(card_paths)
        self.from_resumed = from_resumed
        self.origin_pathspec = origin_pathspec

    def __len__(self):
        return self._high

    def __iter__(self):
        for idx in range(self._high):
            yield self._get_card(idx)

    def __getitem__(self, index):
        return self._get_card(index)

    def _get_card(self, index):
        if index >= self._high:
            raise IndexError
        path = self._card_paths[index]
        card_info = self._card_ds.card_info_from_path(path)
        # todo : find card creation date and put it in client.
        return Card(
            self._card_ds,
            card_info.type,
            path,
            card_info.hash,
            id=card_info.id,
            html=None,
            created_on=None,
        )

    def _make_heading(self, type):
        return "<h1>Displaying Card Of Type : %s</h1>" % type.title()

    def _repr_html_(self):
        main_html = []
        for idx, _ in enumerate(self._card_paths):
            card = self._get_card(idx)
            main_html.append(self._make_heading(card.type))
            container_id = uuid.uuid4()
            main_html.append(
                "<script type='text/javascript'>var mfContainerId = '%s';</script>"
                % container_id
            )
            main_html.append(
                "<div class='embed' data-container='%s'>%s</div>"
                % (container_id, card.get())
            )
        return "\n".join(main_html)


def get_cards(task, id=None, type=None, follow_resumed=True):
    """
    Get cards related to a Metaflow `Task`

    Args:
        task (str or `Task`): A metaflow `Task` object or pathspec (flowname/runid/stepname/taskid)
        type (str, optional): The type of card to retrieve. Defaults to None.
        follow_resumed (bool, optional): If a Task has been resumed and cloned, then setting this flag will resolve the card for the origin task. Defaults to True.

    Returns:
        `CardContainer` : A `list` like object that holds `Card` objects.
    """
    from metaflow.client import Task
    from metaflow import namespace

    card_id = id
    if isinstance(task, str):
        task_str = task
        if len(task_str.split("/")) != 4:
            # Exception that pathspec is not of correct form
            raise IncorrectPathspecException(task_str)
        # set namepsace as None so that we don't face namespace mismatch error.
        namespace(None)
        task = Task(task_str)
    elif not isinstance(task, Task):
        # Exception that the task argument should of form `Task` or `str`
        raise IncorrectArguementException(_TYPE(task))

    if follow_resumed:
        origin_taskpathspec = resumed_info(task)
        if origin_taskpathspec:
            task = Task(origin_taskpathspec)

    card_paths, card_ds = resolve_paths_from_task(
        _get_flow_datastore(task), pathspec=task.pathspec, type=type, card_id=card_id
    )
    return CardContainer(
        card_paths,
        card_ds,
        from_resumed=origin_taskpathspec is not None,
        origin_pathspec=origin_taskpathspec,
    )


def _get_flow_datastore(task):
    flow_name = task.pathspec.split("/")[0]
    # Resolve datastore type
    ds_type = None
    # We need to set the correct datastore root here so that
    # we can ensure the the card client picks up the correct path to the cards

    for meta in task.metadata:
        if meta.name == "ds-type":
            ds_type = meta.value
            break

    ds_root = CardDatastore.get_storage_root(ds_type)

    if ds_root is None:
        for meta in task.metadata:
            # Incase METAFLOW_CARD_S3ROOT and METAFLOW_DATASTORE_SYSROOT_S3 are absent
            # then construct the default path for METAFLOW_CARD_S3ROOT from ds-root metadata
            if meta.name == "ds-root":
                ds_root = os.path.join(meta.value, DATASTORE_CARD_SUFFIX)
                break

    if ds_type is None:
        raise UnresolvableDatastoreException(task)

    storage_impl = DATASTORES[ds_type]
    return FlowDataStore(
        flow_name=flow_name,
        environment=None,  # TODO: Add environment here
        storage_impl=storage_impl,
        # ! ds root cannot be none otherwise `list_content`
        # ! method fails in the datastore abstraction.
        ds_root=ds_root,
    )