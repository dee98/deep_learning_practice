from keras.preprocessing.image import ImageDataGenerator
from keras.layers.pooling import MaxPooling2D, GlobalAveragePooling2D
from keras.layers.core import Dropout, Flatten, Dense
from keras.models import Model
from keras.optimizers import Nadam
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.callbacks import CSVLogger
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from keras.applications.xception import Xception
from keras.applications.inception_v3 import InceptionV3
from keras.applications.inception_resnet_v2 import InceptionResNetV2
from keras.applications.resnet import ResNet50
from keras.applications.nasnet import NASNetLarge
from matplotlib import pyplot as plt
from keras import backend as K
from keras import utils
import numpy as np
import time
import argparse
from os.path import exists
from os import makedirs
from clr_callback import CyclicLR
from keras_efficientnets import EfficientNetB5, EfficientNetB0
from random_eraser import get_random_eraser  # added


MIN_LR = 1e-7
MAX_LR = 1e-2
STEP_SIZE = 8
CLR_METHOD = "triangular"


def cnn_model(model_name, img_size):
    """
    Model definition using Xception net architecture
    """
    input_size = (img_size, img_size, 3)

    if model_name == "xception":
        print("Loading Xception wts...")
        baseModel = Xception(
            weights="imagenet", include_top=False, input_shape=(img_size, img_size, 3)
        )
    elif model_name == "iv3":
        baseModel = InceptionV3(
            weights="imagenet", include_top=False, input_shape=(img_size, img_size, 3)
        )
    elif model_name == "irv2":
        baseModel = InceptionResNetV2(
            weights="imagenet", include_top=False, input_shape=(img_size, img_size, 3)
        )
    elif model_name == "resnet":
        baseModel = ResNet50(
            weights="imagenet", include_top=False, input_shape=(img_size, img_size, 3)
        )
    elif model_name == "nasnet":
        baseModel = NASNetLarge(
            weights="imagenet", include_top=False, input_shape=(img_size, img_size, 3)
        )
    elif model_name == "ef0":
        baseModel = EfficientNetB0(
            input_size, weights="imagenet", include_top=False 
        )
    elif model_name == "ef5":
        baseModel = EfficientNetB5(
            input_size, weights="imagenet", include_top=False 
        )

    
    headModel = baseModel.output
    headModel = GlobalAveragePooling2D()(headModel)
    headModel = Dense(512, activation="relu", kernel_initializer="he_uniform")(
        headModel
    )
    headModel = Dropout(0.4)(headModel)
    # headModel = Dense(512, activation="relu", kernel_initializer="he_uniform")(
    #     headModel
    # )
    # headModel = Dropout(0.5)(headModel)
    predictions = Dense(
        5,
        activation="softmax",
        kernel_initializer="he_uniform")(
        headModel
    )
    model = Model(inputs=baseModel.input, outputs=predictions)

    for layer in baseModel.layers:
        layer.trainable = False

    optimizer = Nadam(
        lr=0.002, beta_1=0.9, beta_2=0.999, epsilon=1e-08, schedule_decay=0.004
    )
    model.compile(
        loss="categorical_crossentropy",
        optimizer=optimizer,
        metrics=["accuracy"]
    )
    return model


def main():
    start = time.time()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-e", "--epochs", required=True, type=int,
        help="Number of epochs", default=25
    )
    ap.add_argument(
        "-m", "--model_name", required=True, type=str,
        help="Imagenet model to train", default="xception"
    )
    ap.add_argument(
        "-b", "--batch_size", required=True, type=int,
        help="Batch size", default=8
    )
    ap.add_argument(
        "-im_size", "--image_size", required=True, type=int,
        help="Batch size", default=224
    )
    args = ap.parse_args()

    # Training dataset loading
    train_data = np.load("train_data.npy")
    train_label = np.load("train_label.npy")
    encoder = LabelEncoder()
    encoder.fit(train_label)
    encoded_y = encoder.transform(train_label)
    Y = utils.to_categorical(encoded_y)

    print("Dataset Loaded...")

    # Train and validation split
    trainX, valX, trainY, valY = train_test_split(
        train_data, Y, test_size=0.1, shuffle=True, random_state=42, stratify=Y
    )
    print(trainX.shape, valX.shape, trainY.shape, valY.shape)

    # Train nad validation image data generator
    trainAug = ImageDataGenerator(
        rescale=1.0 / 255.0,
        preprocessing_function=get_random_eraser(p=0.5, s_l=0.02, s_h=0.4, r_1=0.3, r_2=1/0.3,
                  v_l=0, v_h=255, pixel_level=False),
        rotation_range=30,
        zoom_range=0.15,
        width_shift_range=0.2,
        height_shift_range=0.2,
        shear_range=0.15,
        horizontal_flip=True,
        fill_mode="nearest",
    )

    valAug = ImageDataGenerator(rescale=1.0 / 255.0)

    model = cnn_model(args.model_name, img_size=args.image_size)

    # Number of trainable and non-trainable parameters
    trainable_count = int(
        np.sum([K.count_params(p) for p in set(model.trainable_weights)])
    )
    non_trainable_count = int(
        np.sum([K.count_params(p) for p in set(model.non_trainable_weights)])
    )

    print("Total params: {:,}".format(trainable_count + non_trainable_count))
    print("Trainable params: {:,}".format(trainable_count))
    print("Non-trainable params: {:,}".format(non_trainable_count))

    if not exists("./trained_wts"):
        makedirs("./trained_wts")
    if not exists("./training_logs"):
        makedirs("./training_logs")
    if not exists("./plots"):
        makedirs("./plots")

    # Keras backend
    model_checkpoint = ModelCheckpoint(
        "trained_wts/" + args.model_name + ".hdf5",
        monitor="val_loss",
        verbose=1,
        save_best_only=True,
        save_weights_only=True,
    )

    stopping = EarlyStopping(monitor="val_loss", patience=10, verbose=0)

    clr = CyclicLR(
        mode = CLR_METHOD,
        base_lr = MIN_LR,
        max_lr = MAX_LR,
        step_size = STEP_SIZE * (trainX.shape[0] // args.batch_size)
    )
    print("Training is going to start in 3... 2... 1... ")

    # Model Training
    H = model.fit_generator(
        trainAug.flow(trainX, trainY, batch_size=args.batch_size),
        steps_per_epoch=len(trainX) // args.batch_size,
        validation_data=valAug.flow(valX, valY),
        validation_steps=len(valX) // args.batch_size,
        epochs=args.epochs,
        callbacks=[model_checkpoint],
    )

    # plot the training loss and accuracy
    plt.style.use("ggplot")
    plt.figure()
    N = args.epochs
    plt.plot(np.arange(0, N), H.history["loss"], label="train_loss")
    plt.plot(np.arange(0, N), H.history["val_loss"], label="val_loss")
    plt.plot(np.arange(0, N), H.history["accuracy"], label="train_acc")
    plt.plot(np.arange(0, N), H.history["val_accuracy"], label="val_acc")
    plt.title("Training Loss and Accuracy")
    plt.xlabel("Epoch #")
    plt.ylabel("Loss/Accuracy")
    plt.legend(loc="lower left")
    plt.savefig("plots/training_plot.png")

    N = np.arange(0, len(clr.history["lr"]))
    plt.figure()
    plt.plot(N, clr.history["lr"])
    plt.title("Cyclical Learning Rate (CLR)")
    plt.xlabel("Training Iterations")
    plt.ylabel("Learning Rate")
    plt.savefig("plots/cyclic_lr.png")

    end = time.time()
    dur = end - start

    if dur < 60:
        print("Execution Time:", dur, "seconds")
    elif dur > 60 and dur < 3600:
        dur = dur / 60
        print("Execution Time:", dur, "minutes")
    else:
        dur = dur / (60 * 60)
        print("Execution Time:", dur, "hours")


if __name__ == "__main__":
    main()
