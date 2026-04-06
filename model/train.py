import os
import numpy as np
import tensorflow as tf
from tensorflow import keras
from pathlib import Path

from model import build_embedding_network, SiameseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATASET_DIR = Path('dataset/lfw-deepfunneled/lfw-deepfunneled')
IMG_SIZE = (160, 160)
EMBEDDING_DIM = 128
MARGIN = 0.2

# Batch size should be large so each batch contains many identities,
# giving the hard-mining more useful triplets to work with.
BATCH_SIZE = 128
EPOCHS = 50
LEARNING_RATE = 1e-4

# Only include identities that have at least this many images.
# We need ≥2 so anchor and positive can come from the same person.
MIN_IMAGES_PER_IDENTITY = 2

VAL_RATIO = 0.15
MODEL_SAVE_PATH = 'model/siamese_model.keras'


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_lfw(dataset_dir: Path, min_images: int = 2):
    """
    Walk the LFW directory tree and collect (path, integer_label) pairs.
    Identities with fewer than `min_images` images are excluded because
    they cannot form a positive pair; they are still available as negatives
    in a different split.

    Returns:
        paths          : list of str
        labels         : list of int
        label_to_name  : dict {int -> str}
    """
    paths, labels = [], []
    label_to_name = {}
    label_idx = 0

    for person_dir in sorted(dataset_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        images = sorted(person_dir.glob('*.jpg'))
        if len(images) < min_images:
            continue
        for img_path in images:
            paths.append(str(img_path))
            labels.append(label_idx)
        label_to_name[label_idx] = person_dir.name
        label_idx += 1

    return paths, labels, label_to_name


def split_by_identity(paths, labels, val_ratio=VAL_RATIO, seed=42):
    """
    Split dataset into train / val by identity (not by image), so that no
    person appears in both splits.  This gives a clean evaluation of how
    well the model generalises to unseen identities.
    """
    rng = np.random.default_rng(seed)
    unique_ids = list(set(labels))
    rng.shuffle(unique_ids)
    n_val = max(1, int(len(unique_ids) * val_ratio))
    val_id_set = set(unique_ids[:n_val])

    train_paths, train_labels = [], []
    val_paths, val_labels = [], []

    for path, label in zip(paths, labels):
        if label in val_id_set:
            val_paths.append(path)
            val_labels.append(label)
        else:
            train_paths.append(path)
            train_labels.append(label)

    return train_paths, train_labels, val_paths, val_labels


# ---------------------------------------------------------------------------
# tf.data pipeline
# ---------------------------------------------------------------------------

def preprocess_image(path):
    img = tf.io.read_file(path)
    img = tf.image.decode_jpeg(img, channels=3)
    img = tf.image.resize(img, IMG_SIZE)
    img = tf.cast(img, tf.float32) / 255.0
    return img


def augment_image(img):
    """Light augmentation to improve generalisation."""
    img = tf.image.random_flip_left_right(img)
    img = tf.image.random_brightness(img, max_delta=0.15)
    img = tf.image.random_contrast(img, lower=0.85, upper=1.15)
    return tf.clip_by_value(img, 0.0, 1.0)


def build_dataset(paths, labels, batch_size, augment=False, shuffle=True):
    ds = tf.data.Dataset.from_tensor_slices(
        (tf.constant(paths), tf.constant(labels, dtype=tf.int32))
    )
    if shuffle:
        ds = ds.shuffle(buffer_size=len(paths), reshuffle_each_iteration=True)

    def load(path, label):
        img = preprocess_image(path)
        if augment:
            img = augment_image(img)
        return img, label

    ds = ds.map(load, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(batch_size, drop_remainder=True)
    ds = ds.prefetch(tf.data.AUTOTUNE)
    return ds


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

class SaveEmbeddingNetwork(keras.callbacks.Callback):
    """Saves only the embedding_network (not the SiameseModel wrapper) when
    val_loss improves.  The embedding network is the only part needed for
    inference, and it serialises cleanly without get_config() overrides."""

    def __init__(self, embedding_network, save_path):
        super().__init__()
        self.embedding_network = embedding_network
        self.save_path = save_path
        self.best_val_loss = float('inf')

    def on_epoch_end(self, epoch, logs=None):
        val_loss = logs.get('val_triplet_loss', float('inf'))
        if val_loss < self.best_val_loss:
            self.best_val_loss = val_loss
            self.embedding_network.save(self.save_path)
            print(f'\nEpoch {epoch + 1}: val_triplet_loss improved to {val_loss:.5f}, '
                  f'saving embedding network to {self.save_path}')


if __name__ == '__main__':
    # --- GPU / CPU detection ------------------------------------------------
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        print(f'Training on GPU: {gpus[0].name}')
        # Allow memory growth so TF doesn't allocate all VRAM at once
        tf.config.experimental.set_memory_growth(gpus[0], True)
    else:
        print('No GPU found — training on CPU')

    # --- Load & split -------------------------------------------------------
    print('Loading LFW dataset...')
    paths, labels, label_to_name = load_lfw(DATASET_DIR, MIN_IMAGES_PER_IDENTITY)
    n_identities = len(label_to_name)
    print(f'  {len(paths)} images across {n_identities} identities')

    train_paths, train_labels, val_paths, val_labels = split_by_identity(paths, labels)
    print(f'  Train: {len(train_paths)} images | Val: {len(val_paths)} images')

    train_ds = build_dataset(train_paths, train_labels, BATCH_SIZE, augment=True)
    val_ds = build_dataset(val_paths, val_labels, BATCH_SIZE, augment=False, shuffle=False)

    # --- Build model --------------------------------------------------------
    embedding_net = build_embedding_network(
        input_shape=(*IMG_SIZE, 3),
        embedding_dim=EMBEDDING_DIM,
    )
    embedding_net.summary()

    model = SiameseModel(embedding_net, n_classes=n_identities, margin=MARGIN)
    model.compile(optimizer=keras.optimizers.Adam(LEARNING_RATE))

    # --- Callbacks ----------------------------------------------------------
    os.makedirs(os.path.dirname(MODEL_SAVE_PATH), exist_ok=True)

    callbacks = [
        # Save embedding network when val_loss improves
        SaveEmbeddingNetwork(embedding_net, MODEL_SAVE_PATH),
        # Halve the learning rate when val_triplet_loss stops improving
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_triplet_loss',
            mode='min',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1,
        ),
        # Stop early if no improvement for 15 epochs
        keras.callbacks.EarlyStopping(
            monitor='val_triplet_loss',
            mode='min',
            patience=15,
            restore_best_weights=True,
            verbose=1,
        ),
    ]

    # --- Train --------------------------------------------------------------
    print('\nStarting training...')
    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS,
        callbacks=callbacks,
    )

    print(f'\nTraining complete. Best model saved to: {MODEL_SAVE_PATH}')
