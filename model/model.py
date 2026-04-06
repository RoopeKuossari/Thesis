import tensorflow as tf
from tensorflow import keras


def build_embedding_network(input_shape=(160, 160, 3), embedding_dim=128):
    """
    Custom CNN that maps a face image to an L2-normalized embedding vector.

    Architecture: 4 convolutional blocks (Conv → BN → ReLU → MaxPool)
    followed by GlobalAveragePooling and two dense layers.
    The final L2 normalization constrains all embeddings to the unit hypersphere,
    which makes cosine similarity equivalent to dot product and stabilizes
    triplet loss training.
    """
    inputs = keras.Input(shape=input_shape, name='input_image')

    # Block 1 — low-level features (edges, textures)
    x = keras.layers.Conv2D(32, 3, padding='same', name='conv1')(inputs)
    x = keras.layers.BatchNormalization(name='bn1')(x)
    x = keras.layers.ReLU(name='relu1')(x)
    x = keras.layers.MaxPooling2D(name='pool1')(x)          # → 80×80

    # Block 2
    x = keras.layers.Conv2D(64, 3, padding='same', name='conv2')(x)
    x = keras.layers.BatchNormalization(name='bn2')(x)
    x = keras.layers.ReLU(name='relu2')(x)
    x = keras.layers.MaxPooling2D(name='pool2')(x)          # → 40×40

    # Block 3 — mid-level features (facial parts)
    x = keras.layers.Conv2D(128, 3, padding='same', name='conv3')(x)
    x = keras.layers.BatchNormalization(name='bn3')(x)
    x = keras.layers.ReLU(name='relu3')(x)
    x = keras.layers.MaxPooling2D(name='pool3')(x)          # → 20×20

    # Block 4 — high-level features (identity-specific patterns)
    x = keras.layers.Conv2D(256, 3, padding='same', name='conv4')(x)
    x = keras.layers.BatchNormalization(name='bn4')(x)
    x = keras.layers.ReLU(name='relu4')(x)
    x = keras.layers.MaxPooling2D(name='pool4')(x)          # → 10×10

    # Embedding head
    x = keras.layers.GlobalAveragePooling2D(name='gap')(x)
    x = keras.layers.Dense(512, name='fc1')(x)
    x = keras.layers.ReLU(name='relu_fc1')(x)
    x = keras.layers.Dropout(0.3, name='dropout')(x)
    x = keras.layers.Dense(embedding_dim, name='embedding')(x)

    # L2 normalize so all embeddings live on the unit hypersphere
    outputs = keras.layers.UnitNormalization(axis=-1, name='l2_normalize')(x)

    return keras.Model(inputs, outputs, name='embedding_network')


def batch_hard_triplet_loss(labels, embeddings, margin=0.2):
    """
    Batch-hard triplet loss with online mining.

    For every anchor in the batch:
      - hardest positive  = same-identity sample with the LARGEST distance
      - hardest negative  = different-identity sample with the SMALLEST distance

    Loss = mean(max(d(a,p) - d(a,n) + margin, 0))

    Only anchors that have at least one valid positive in the batch contribute
    to the loss, so batches can safely contain single-image identities (they
    act as negatives only).
    """
    dot = tf.matmul(embeddings, tf.transpose(embeddings))
    sq_norm = tf.linalg.diag_part(dot)
    distances = (
        tf.expand_dims(sq_norm, 1)
        - 2.0 * dot
        + tf.expand_dims(sq_norm, 0)
    )
    distances = tf.sqrt(tf.maximum(distances, 1e-12))

    labels = tf.cast(labels, tf.int32)
    same_identity = tf.equal(
        tf.expand_dims(labels, 0), tf.expand_dims(labels, 1)
    )
    eye = tf.cast(tf.eye(tf.shape(labels)[0], dtype=tf.bool), tf.bool)

    valid_positive = tf.logical_and(same_identity, tf.logical_not(eye))
    valid_negative = tf.logical_not(same_identity)

    pos_distances = distances * tf.cast(valid_positive, tf.float32)
    hardest_positive = tf.reduce_max(pos_distances, axis=1)

    max_dist = tf.reduce_max(distances)
    neg_distances = (
        distances
        + max_dist * tf.cast(tf.logical_not(valid_negative), tf.float32)
    )
    hardest_negative = tf.reduce_min(neg_distances, axis=1)

    triplet_loss = tf.maximum(hardest_positive - hardest_negative + margin, 0.0)

    has_positive = tf.reduce_any(valid_positive, axis=1)
    triplet_loss = tf.boolean_mask(triplet_loss, has_positive)

    return tf.reduce_mean(triplet_loss)


class SiameseModel(keras.Model):
    """
    Trains the embedding network with a combined loss:

        total_loss = triplet_loss + alpha * cross_entropy_loss

    The classification head (embedding → n_classes) is only used during
    training. It forces the network to produce discriminative embeddings
    and prevents the collapse-to-constant failure mode of pure triplet loss.
    At inference only the embedding_network is used.

    Args:
        embedding_network : Keras Model, input → 128-dim L2 embedding
        n_classes         : number of training identities
        margin            : triplet loss margin (default 0.2)
        alpha             : weight of the classification loss (default 0.5)
    """

    def __init__(self, embedding_network, n_classes, margin=0.2, alpha=0.5):
        super().__init__()
        self.embedding_network = embedding_network
        self.margin = margin
        self.alpha = alpha

        # Classification head — only active during training
        self.classifier = keras.layers.Dense(n_classes, name='classifier')

        self.loss_tracker = keras.metrics.Mean(name='loss')
        self.triplet_tracker = keras.metrics.Mean(name='triplet_loss')
        self.cls_tracker = keras.metrics.Mean(name='cls_loss')

    def call(self, inputs, training=False):
        return self.embedding_network(inputs, training=training)

    def train_step(self, data):
        images, labels = data
        with tf.GradientTape() as tape:
            embeddings = self.embedding_network(images, training=True)

            # Triplet loss — pushes same-identity together, others apart
            t_loss = batch_hard_triplet_loss(labels, embeddings, self.margin)

            # Classification loss — prevents embedding collapse
            logits = self.classifier(embeddings, training=True)
            c_loss = tf.reduce_mean(
                keras.losses.sparse_categorical_crossentropy(
                    labels, logits, from_logits=True
                )
            )

            total = t_loss + self.alpha * c_loss

        trainable_vars = (
            self.embedding_network.trainable_variables
            + self.classifier.trainable_variables
        )
        gradients = tape.gradient(total, trainable_vars)
        self.optimizer.apply_gradients(zip(gradients, trainable_vars))

        self.loss_tracker.update_state(total)
        self.triplet_tracker.update_state(t_loss)
        self.cls_tracker.update_state(c_loss)
        return {m.name: m.result() for m in self.metrics}

    def test_step(self, data):
        images, labels = data
        embeddings = self.embedding_network(images, training=False)
        t_loss = batch_hard_triplet_loss(labels, embeddings, self.margin)
        logits = self.classifier(embeddings, training=False)
        c_loss = tf.reduce_mean(
            keras.losses.sparse_categorical_crossentropy(
                labels, logits, from_logits=True
            )
        )
        total = t_loss + self.alpha * c_loss
        self.loss_tracker.update_state(total)
        self.triplet_tracker.update_state(t_loss)
        self.cls_tracker.update_state(c_loss)
        return {m.name: m.result() for m in self.metrics}

    @property
    def metrics(self):
        return [self.loss_tracker, self.triplet_tracker, self.cls_tracker]
