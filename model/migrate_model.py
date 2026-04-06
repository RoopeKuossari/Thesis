"""
One-time migration: extracts weights directly from the .keras zip archive
(bypassing the broken Lambda layer config) and re-saves them into the fixed
UnitNormalization architecture.

Run once:
    python model/migrate_model.py
"""
import zipfile
import shutil
import numpy as np
import tensorflow as tf
from model import build_embedding_network

OLD_PATH = 'model/siamese_model.keras'
NEW_PATH = 'model/siamese_model.keras'
WEIGHTS_TMP = 'model/_tmp_weights.weights.h5'

# Step 1: extract the weights file from the .keras zip archive
print('Extracting weights from archive...')
with zipfile.ZipFile(OLD_PATH, 'r') as zf:
    # Keras 3 stores weights as 'model.weights.h5' inside the zip
    weights_filename = next(n for n in zf.namelist() if n.endswith('.weights.h5'))
    with zf.open(weights_filename) as src, open(WEIGHTS_TMP, 'wb') as dst:
        shutil.copyfileobj(src, dst)

# Step 2: build the fixed architecture
print('Building fixed architecture...')
new_model = build_embedding_network(input_shape=(160, 160, 3), embedding_dim=128)

# Initialise weights by doing a dummy forward pass
new_model(np.zeros((1, 160, 160, 3), dtype=np.float32))

# Step 3: load the extracted weights by layer name
print('Loading weights into fixed architecture...')
new_model.load_weights(WEIGHTS_TMP, skip_mismatch=True)

# Step 4: save the fixed model
print(f'Saving to {NEW_PATH}...')
new_model.save(NEW_PATH)

import os
os.remove(WEIGHTS_TMP)
print('Done. Migration complete.')
