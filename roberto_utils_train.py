import os
import logging
import datetime
import shutil

import dtlpy as dl
from dtlpy.ml.train_utils import prepare_dataset

logger = logging.getLogger(name=__name__)


class ServiceRunner(dl.BaseServiceRunner):
    """
    Package runner class
    """

    def __init__(self):
        """

        """
        pass

    def train(self, snapshot: dl.Snapshot, progress: dl.Progress = None):
        return self.train_on_snapshot(snapshot=snapshot, progress=progress)

    def train_on_snapshot(self,
                          snapshot: dl.Snapshot,
                          cleanup=False,
                          progress: dl.Progress = None):
        # FROM PARENT
        """
            Train on existing snapshot.
            data will be taken from snapshot.datasetId
            configuration is as defined in snapshot.configuration
            upload the output the the snapshot's bucket (snapshot.bucket)
        """

        logger.info("Recieved {s} for training".format(s=snapshot.id))

        def on_epoch_end(epoch, n_epoch):
            if progress is not None:
                progress.update(message='training epoch: {}/{}'.format(epoch, n_epoch), progress=epoch / n_epoch)

        adapter = self._create_and_load_adapter(snapshot=snapshot)

        root_path, data_path, output_path = adapter.prepare_training(
            root_path=os.path.join('tmp', snapshot.id))
        # Start the Train
        logger.info("Training {m_name!r} with snapshot {s_name!r} on data {d_path!r}".
                    format(m_name=adapter.model_name, s_name=snapshot.id, d_path=data_path))
        if progress is not None:
            progress.update(message='starting training')

        adapter.train(data_path=data_path,
                      output_path=output_path,
                      on_epoch_end=on_epoch_end)
        if progress is not None:
            progress.update(message='saving snapshot', progress=95 / 100)

        adapter.save_to_snapshot(local_path=output_path, replace=True)

        ###########
        # cleanup #
        ###########
        if cleanup:
            shutil.rmtree(output_path, ignore_errors=True)

        return adapter.snapshot

    def train_from_dataset(self,
                           from_snapshot: dl.Snapshot,
                           dataset: dl.Dataset,
                           filters=None,
                           # new training params
                           snapshot_name=None,
                           configuration=None,
                           progress: dl.Progress = None):
        """
            Create a cloned snapshot from dataset
            Train using new snapshot

        Args:
            from_snapshot (dl.Snapshot, optional): What is the `source` Snapshot to clone from
            dataset (dl.Dataset): source dataset
            filters (dl.Filters, optional): how to create the cloned dataset. Defaults to None.
            snapshot_name (str, optional): New cloned snapshot name. Defaults to None==> <model_name>-<dataset_name>-<YYMMDD-HHMMSS>.
            configuration (dict, optional): updated configuration in the cloned snapshot. Defaults to None.
            progress (dl.Progress, optional): [description]. Defaults to None.

        Returns:
            dl.Snapshot: Cloned snapshot
        """
        logger.info("Recieved a dataset {d!r} to train from".format(d=dataset.id))
        snapshot = self.clone_snapshot_from_dataset(
            dataset=dataset,
            filters=filters,
            from_snapshot=from_snapshot,
            snapshot_name=snapshot_name,
            configuration=configuration,
            progress=progress
        )

        return self.train_on_snapshot(snapshot=snapshot,
                                      progress=progress)

    def clone_snapshot_from_dataset(self,
                                    from_snapshot: dl.Snapshot,
                                    dataset: dl.Dataset,
                                    filters=None,
                                    # new training params
                                    snapshot_name=None,
                                    configuration=None,
                                    progress: dl.Progress = None):
        """Creates a new snapshot from dataset
            Functionality is split - for the use from UI


        Args:
            from_snapshot (dl.Snapshot, optional): What is the `source` Snapshot to clone from
            dataset (dl.Dataset): source dataset
            filters (dl.Filters, optional): how to create the cloned dataset. Defaults to None.
            snapshot_name (str, optional): New cloned snapshot name. Defaults to None==> <model_name>-<dataset_name>-<YYMMDD-HHMMSS>.
            configuration (dict, optional): updated configuration in the cloned snapshot. Defaults to None.
            progress (dl.Progress, optional): [description]. Defaults to None.

        Returns:
            dl.Snapshot: Cloned snapshot
        """
        logger.info("Recieved a dataset {d!r} to use in cloned version of orig snapshot {s!r} ".
                    format(d=dataset.id, s=from_snapshot.id))
        # Base entities
        model = from_snapshot.model
        project = dataset.project  # This is the destenation project

        if isinstance(filters, dict):
            t_filters = filters
            filters = dl.Filters()
            filters.custom_filter = t_filters
        if progress is not None:
            progress.update(message='preparing dataset', progress=5 / 100)

        partitions = {dl.SnapshotPartitionType.TRAIN: 0.8,
                      dl.SnapshotPartitionType.VALIDATION: 0.2}
        cloned_dataset = prepare_dataset(dataset,
                                         partitions=partitions,
                                         filters=filters)
        if snapshot_name is None:
            snapshot_name = '{}-{}-{}'.format(model.name,
                                              cloned_dataset.name,
                                              datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        if configuration is None:
            configuration = dict()

        if progress is not None:
            progress.update(message='creating snapshot', progress=10 / 100)

        bucket = project.buckets.create(bucket_type=dl.BucketType.ITEM,
                                        model_name=model.name,
                                        snapshot_name=snapshot_name)
        cloned_snapshot = from_snapshot.clone(snapshot_name=snapshot_name,
                                              configuration=configuration,
                                              bucket=bucket,
                                              project_id=project.id,
                                              dataset_id=cloned_dataset.id)
        return cloned_snapshot

    def _create_and_load_adapter(self, model: dl.Model = None, snapshot: dl.Snapshot = None):
        """create and load the adapter based on the model and snapshot - Must provide at least one

        Args:
            model (dl.Model, optional): which model to use. Defaults to None ==> uses snapshot.model.
            snapshot (dl.Snapshot, optional): which snapshot to load the adapter with. Defaults to None.

        Returns:
            [type]: [description]
        """

        if model is None:
            model = snapshot.model

        logger.info("Building Model {n} ({i!r})".format(n=model.name, i=model.id))
        adapter = model.build()

        if snapshot is not None:
            logger.info("Loading Adapter with: {n} ({i!r})".format(n=snapshot.name, i=snapshot.id))
            logger.debug("Snapshot\n{}\n{}".format('=' * 8, snapshot.print(to_return=True)))
            adapter.load_from_snapshot(snapshot)

        return adapter

    def execution_wrapper(self, config):
        """Wrapper for execution sent from UI
            from Fadi w/ Love

        e.g. : {'function': 'train_on_snapshot', 'snapshot': <snapshot_id>}

        Args:
            config (dict): json dict that holds the resource and what function to run
        """

        logger.debug("GOT config: {}".format(config))
        logger.warning("HI I GOT to this line....")

        # GET THE FUNCTION NAME
        if 'function' in config:
            func = config.get('function')
        else:
            func = config.get('func')

        if func == 'train_on_snapshot':
            snapshot = dl.snapshots.get(snapshot_id=config.get('snapshot'))
            return self.train_on_snapshot(snapshot=snapshot)

        elif func == 'train_from_dataset':
            dataset = dl.datasets.get(dataset_id=config.get('dataset'))
            return self.train_from_dataset(
                dataset=dataset,
                filters=config.get('filters')
            )
        else:
            raise RuntimeError("ROBERTO-UTILS-TRAIN Error: Function {!r} not supported by wrapper".format(func))


def train_yolox_test(env='prod'):
    # FIXME: yolox is not in the project
    # inputs
    import logging
    logging.basicConfig(level='INFO')
    dl.setenv(env)
    project = dl.projects.get(project_name='COCO ors')
    model = project.models.get(model_name='YOLOX')
    ##############################
    ################## all should be in function
    # FIXME - package changed - we need to refactor code
    self = ServiceRunner(project_name=project.name,
                         model_name=model.name,
                         snapshot_name='coco-pretrained')

    ########################
    #########################
    snapshot_name = 'second-fruit'
    # delete if exists
    try:
        snap = model.snapshots.get(snapshot_name=snapshot_name)
        snap.dataset.delete(sure=True, really=True)
        snap.delete()
    except:
        pass

    dataset = project.datasets.get(dataset_name='FruitImage')
    configuration = {'batch_size': 2,
                     'start_epoch': 0,
                     'max_epoch': 5,
                     'input_size': (256, 256)}

    self.train_from_dataset(dataset=dataset,
                            filters=dict(),
                            snapshot_name=snapshot_name,
                            configuration=configuration)


def train_yolov5_test(env='rc'):
    # inputs
    import logging
    logging.basicConfig(level='INFO')
    dl.setenv(env)
    project_name = 'DataloopModels'
    model_name = 'yolo-v5'
    snapshot_name = 'pretrained-yolo-v5-small'

    project = dl.projects.get(project_name=project_name)
    model = project.models.get(model_name=model_name)
    pretrained_snapshot = model.snapshots.get(snapshot_name=snapshot_name)

    ####################
    # Destenation params
    ####################
    dst_project = dl.projects.get(project_name='roberto-sandbox')
    dataset = dst_project.datasets.get(dataset_name='ds-2-frozen')
    dst_snapshot_name = 'snap-utils-train'
    # delete if exists
    try:
        snap = dst_project.snapshots.get(snapshot_name=snapshot_name)
        print("Found snapshot - deleting dataset and snapshot")
        snap.dataset.delete(sure=True, really=True)
        snap.delete()
    except:
        pass

    ##############################
    ################## all should be in function
    runner = ServiceRunner()

    configuration = {'batch_size': 2,
                     'num_epochs': 3,
                     }

    dst_snapshot = runner.train_from_dataset(
        from_snapshot=pretrained_snapshot,
        dataset=dataset,
        filters=dict(),
        snapshot_name=dst_snapshot_name,
        configuration=configuration
    )
    print("Returned snapshot")
    print(dst_snapshot.print(to_return=False))


if __name__ == '__main__':
    print("Test function")
    # train_yolox_test()
    train_yolov5_test()
