#!/bin/bash

set -x

curl -X POST http://124.70.103.32:5000/api/receive \
-H "Content-Type: application/json" \
-d '{
    "IdNumber": "2019070111201",
    "MessageId": "1",
    "Content": "A430373A34363A32304E323831342E31323538364531313235322E36303137322B30303037382E302DC4E3BAC354455354",
    "Time": "2021-12-16 10:30:33",
    "DeliveryCount": "1",
    "NetworkMode": "BD"
}'

curl -X POST http://124.70.103.32:5000/api/receive \
-H "Content-Type: application/json" \
-d '{
    "IdNumber": "202310130001",
    "MessageId": "2",
    "Content": "A431303A33303A31354E343030352E37363738334531313632312E35373739382B30303039392E352DB0B2C8ABB5BDB4EF303031",
    "Time": "2023-10-13 09:00:00",
    "DeliveryCount": "2",
    "NetworkMode": "BD"
}'

curl -X POST http://124.70.103.32:5000/api/receive \
-H "Content-Type: application/json" \
-d '{
    "IdNumber": "202310130002",
    "MessageId": "3",
    "Content": "A430323A34333A32354E323831332E39333731304531313235322E34383430332B30303438332E302DC4E3BAC354455354",
    "Time": "2023-10-13 10:00:00",
    "DeliveryCount": "1",
    "NetworkMode": "BD"
}'

curl -X POST http://124.70.103.32:5000/api/receive \
-H "Content-Type: application/json" \
-d '{
    "IdNumber": "202310130021",
    "MessageId": "3",
    "Content": "A431303A30323A30304E323831342E31323733374531313235322E36303432332B30303036302E352DC4E3BAC354455354",
    "Time": "2023-10-13 10:00:00",
    "DeliveryCount": "1",
    "NetworkMode": "BD"
}'

