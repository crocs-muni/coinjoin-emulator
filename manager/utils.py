def batched(data, batch_size=1):
    length = len(data)
    for ndx in range(0, length, batch_size):
        yield data[ndx : min(ndx + batch_size, length)]
