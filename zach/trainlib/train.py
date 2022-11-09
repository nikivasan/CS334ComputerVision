import copy
import sys
import math
from datetime import datetime
import random
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import backend as K
from tensorflow.keras.optimizers import Adam,RMSprop,SGD
from tensorflow.keras.layers import concatenate, add, GlobalAveragePooling2D, BatchNormalization, Input, Dense, Activation, Dropout, Flatten
from tensorflow.keras.models import Model
from tensorflow.keras.callbacks import EarlyStopping, LearningRateScheduler, ReduceLROnPlateau, ModelCheckpoint
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.applications.densenet import DenseNet121
from tensorflow.keras.preprocessing.image import load_img
from tensorflow.keras import optimizers
import pickle
import os
import json
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import argparse

# Returns configuration in dictionary format.
def load_config(config_path):
    with open(config_path, 'r') as f:
        config = json.load(f)

    return config

def modify_paths(base_path, relative_path):
    return os.path.join(base_path, relative_path)

# Returns DataFrame objects corresponding to train, validation, and test sets with path modified
# relative to the image paths. This function assumes the respective csvs are called train.csv, valid.csv,
# and test.csv. It also assumes there is a path variable with the relative path to the images.
def load_datasets(config):
    csv_base = config['META_BASE_PATH']
    image_base = config['IMAGE_BASE_PATH']
    train = pd.read_csv(os.path.join(csv_base, 'train.csv'))
    valid = pd.read_csv(os.path.join(csv_base, 'valid.csv'))
    test = pd.read_csv(os.path.join(csv_base, 'test.csv'))
    train['path'] = train['path'].apply(lambda x: modify_paths(image_base, x))
    valid['path'] = valid['path'].apply(lambda x: modify_paths(image_base, x))
    test['path'] = test['path'].apply(lambda x: modify_paths(image_base, x))

    return train, valid, test

# Yields labels in required format.
def generator_wrapper(generator, num_classes):
    for batch_x,batch_y in generator:
        yield (batch_x,[batch_y[:,i] for i in range(num_classes)])


# Returns image data generators for train, valid, and test splits.
def get_image_generators(train, valid, test, config):

    HEIGHT = config['IMG_HEIGHT']
    WIDTH = config['IMG_WIDTH']
    BATCH_SIZE = config['BATCH_SIZE']
    TEST_BATCH = config['TEST_BATCH']
    num_classes = config['NUM_CLASSES']

    labels = 'Atelectasis,Cardiomegaly,Consolidation,Edema,Enlarged Cardiomediastinum,Fracture,Lung Lesion,Lung Opacity,No Finding,Pleural Effusion,Pleural Other,Pneumonia,Pneumothorax,Support Devices'.split(',')
    print(f"Num labels {str(len(labels))}", flush=True)

    train_gen = ImageDataGenerator(
            rotation_range=15,
            fill_mode='constant',
            zoom_range=0.1,
            horizontal_flip=True,
            rescale = 1./255
    )

    validate_gen = ImageDataGenerator(rescale = 1./255)

    train_batches = train_gen.flow_from_dataframe(
        train,
        directory=None,
        x_col="path",
        y_col=labels,
        class_mode="raw",
        target_size=(HEIGHT, WIDTH),
        shuffle=True,
        seed=1,
        batch_size=BATCH_SIZE
    )

    validate_batches = validate_gen.flow_from_dataframe(
        valid,
        directory=None,
        x_col="path",
        y_col=labels,
        class_mode="raw",
        target_size=(HEIGHT, WIDTH),
        shuffle=True,
        batch_size=BATCH_SIZE
    )

    test_batches = validate_gen.flow_from_dataframe(
        test,
        directory=None,
        x_col="path",
        y_col=labels,
        class_mode="raw",
        target_size=(HEIGHT, WIDTH),
        shuffle=False,
        batch_size=TEST_BATCH
    )

    return generator_wrapper(train_batches, num_classes), generator_wrapper(validate_batches, num_classes), generator_wrapper(test_batches, num_classes)

def get_model(num_classes):
    
    base_model = DenseNet121(weights='imagenet', include_top=False)
    x = base_model.output
    x = Dense(512, activation = 'relu')(x)
    x = Dropout(0.3)(x)

    # Add an individual classification layer for every class.
    output = []
    for i in range(num_classes):
        output.append(Dense(1, activation='sigmoid')(x))
    
    model = Model(inputs=base_model.input, outputs=output)

    return model

def train_model(model, train_ds, valid_ds, config):

    BATCH_SIZE = config['BATCH_SIZE']
    TEST_BATCH = config['TEST_BATCH']
    lr = config['INITIAL_LR']
    epochs = config['MAX_EPOCHS']
    weights_dir = config['WEIGHTS_DIR']

    train_epoch = math.ceil(len(train) / BATCH_SIZE)
    val_epoch = math.ceil(len(valid) / BATCH_SIZE)

    losses = ['binary_crossentropy' for i in range(config['NUM_CLASSES'])]
    print(losses)
    # Need to compile model with an individual loss function for each layer.
    model.compile(optimizer=Adam(lr),
        loss=losses,
        metrics=[
            tf.keras.metrics.Accuracy(), 
            tf.keras.metrics.AUC(multi_label=True)
        ]
    )

    reduce_lr = ReduceLROnPlateau(monitor='val_loss', mode='min', factor=0.1,
                                patience=2, min_lr=1e-6, verbose=1)
    ES = EarlyStopping(monitor='val_loss', mode='min', patience=4, restore_best_weights=True)

    if not os.path.exists(weights_dir):
        os.makedirs(weights_dir)
    
    weights_path = os.path.join(weights_dir, 'model.hdf5')

    checkloss = ModelCheckpoint(weights_path, monitor='val_loss', mode='min', verbose=1, save_best_only=True, save_weights_only=False)

    history = model.fit(train_ds,
        validation_data=valid_ds,
        steps_per_epoch=train_epoch,
        validation_steps=val_epoch,
        epochs=epochs,
        shuffle=True,
        callbacks=[reduce_lr, checkloss, ES]
    )

    return history

if __name__ == '__main__':

    config = load_config('config.json')
    train, valid, test = load_datasets(config)

    train_batches, valid_batches, test_batches = get_image_generators(train, valid, test, config)

    num_classes = config['NUM_CLASSES']
    model = get_model(num_classes)

    history = train_model(model, train_batches, valid_batches, config)

    # Predict on test set.
    Y_pred = model.predict(test_batches)

    # Save pickle files of training history and predictions for further analysis.
    with open('predictions', 'wb') as f:
        pickle.dump(Y_pred, f)

    with open('train_hist', 'wb') as file_pi:
            pickle.dump(history.history, file_pi)

