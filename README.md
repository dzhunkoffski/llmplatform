# llmplatform
Simple overview of use/purpose.

## Description

An in-depth paragraph about your project and overview of use.

## Getting Started

### Dependencies

* Describe any prerequisites, libraries, OS version, etc., needed before installing program.
* ex. Windows 10

### Installing

* How/where to download your program
* Any modifications needed to be made to files/folders

### Executing program

* Check that balancer is alive
```bash
curl http://localhost:8000/health
```
* Send this prompt to test the platform
```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{
  "model": "qwen:0.5b",
  "messages": [
    {
      "role": "user",
      "content": "Что такое балансировщик нагрузки?"
    }
  ],
  "stream": true
}'
```

## Help

Any advise for common problems or issues.
```
command to run if program contains helper info
```

## Authors

Contributors names and contact info

ex. Dominique Pizzie  
ex. [@DomPizzie](https://twitter.com/dompizzie)