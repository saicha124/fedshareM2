import pickle
import sys
import threading

import numpy as np
from flask import Flask, request

import flcommon
import mnistcommon
import time_logger
from config import ClientConfig

config = ClientConfig(int(sys.argv[1]))

client_datasets = mnistcommon.load_train_dataset(config.number_of_clients, permute=True)

api = Flask(__name__)

total_upload_cost = 0
total_download_cost = 0

training_round = 0


def start_next_round(data):
    time_logger.client_start()

    x_train, y_train = client_datasets[config.client_index][0], client_datasets[config.client_index][1]

    model = mnistcommon.get_model()

    global training_round
    if training_round != 0:
        round_weight = pickle.loads(data)
        model.set_weights(round_weight)

    print(
        f"Model: FedAvg, "
        f"Round: {training_round + 1}/{config.training_rounds}, "
        f"Client {config.client_index + 1}/{config.number_of_clients}, "
        f"Dataset Size: {len(x_train)}")
    model.fit(x_train, y_train, epochs=config.epochs, batch_size=config.batch_size, verbose=config.verbose,
              validation_split=config.validation_split)
    
    # Evaluate local client performance on test data
    x_test, y_test = mnistcommon.load_test_dataset()
    local_results = model.evaluate(x_test, y_test, verbose=0)
    local_loss = local_results[0]
    local_accuracy = local_results[1]
    
    print(f"Client {config.client_index} Local Performance:")
    print(f"  loss: {local_loss:.6f}")
    print(f"  accuracy: {local_accuracy:.6f}")
    
    # Get model weights and handle different shapes properly
    model_weights = model.get_weights()
    
    layers = []
    for weight_array in model_weights:
        layers.append(weight_array.astype('float64'))

    pickle_model = pickle.dumps(layers)  # Send as list, not array

    flcommon.send_to_fedavg_server(pickle_model, config)

    len_serialized_model = len(pickle_model)
    global total_upload_cost
    total_upload_cost += len_serialized_model

    print(f"[Upload] Size of the object to send to server is {len_serialized_model}")
    print(f"Sent {training_round} to server")

    global total_download_cost
    print(f"[DOWNLOAD] Total download cost so far: {total_download_cost}")
    print(f"[UPLOAD] Total upload cost so far: {total_upload_cost}")

    training_round += 1
    print(f"********************** Round {training_round} completed **********************")
    print("Waiting to receive response from server...")
    time_logger.client_idle()


@api.route('/recv', methods=['POST'])
def recv():
    my_thread = threading.Thread(target=recv_thread, args=(request.data, ))
    my_thread.start()
    return {"response": "ok"}


@api.route('/start', methods=['GET'])
def start():
    time_logger.start_training()
    my_thread = threading.Thread(target=start_next_round, args=(0, ))
    my_thread.start()
    return {"response": "ok"}


def recv_thread(data):
    global total_download_cost
    total_download_cost += len(data)

    global training_round
    if config.training_rounds == training_round:
        # Evaluate global performance on the final aggregated model
        final_weights = pickle.loads(data)
        flcommon.evaluate_global_performance("FedAvg", final_weights, mnistcommon.get_model)
        
        time_logger.finish_training()
        time_logger.print_result()

        print(f"[DOWNLOAD] Total download cost so far: {total_download_cost}")
        print(f"[UPLOAD] Total upload cost so far: {total_upload_cost}")

        print("Training finished.")
        return

    start_next_round(data,)


api.run(host=flcommon.get_ip(config), port=config.client_base_port + int(sys.argv[1]), debug=False, threaded=True, use_reloader=False)
