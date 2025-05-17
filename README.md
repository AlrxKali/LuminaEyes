# LuminaEyes

# Phase 0: Core Foundation & Minimal Viable Streaming (Proof of Concept to MVP)
**Objective:** Establish a secure, basic WebRTC video stream from a single, representative camera type (e.g., an RTSP camera) to a backend service, and view this stream in a minimal client. This validates the core streaming technology.

### Components to Build (Minimal Versions):
1. **Basic Camera Ingestion/Edge Agent:** Connects to one RTSP camera, fetches the stream, and acts as a WebRTC client.
2. **Basic WebRTC Signaling Server:** Handles offer/answer/ICE candidate exchange for one connection.
3. **Basic Video Processing Backend (WebRTC Peer):** Acts as the WebRTC server, receives the stream.
4. **Minimal Stream Viewer:** A very simple web page or test application that can connect as a WebRTC peer to the Video Processing Backend to display the received video. (Alternatively, the VPB could just log frame reception).

### Key Functionalities:
* Connect to a single RTSP camera.
* Establish a WebRTC connection between the Ingestion Agent and the Video Processing Backend.
* Securely stream video (SRTP).
* Display the live video stream in the minimal viewer (or confirm reception at the backend).

### Quality & Security Focus:
* Secure WebRTC connection setup (DTLS, SRTP).
* Secure WebSocket (WSS) for signaling.
* Basic error handling and logging for connection issues.
* Hardcoded credentials initially (for PoC only), but plan for secure secret management.

### Best Practices Highlight:
* Version control (Git) from day one.
* Choose foundational libraries for WebRTC (e.g., Pion, aiortc, libWebRTC) and signaling.

# Phase 1: Basic Computer Vision Integration & API Scaffolding
**Objective:** Integrate a single, simple CV model to process the incoming video stream and expose results via a basic API.

### Components to Build/Enhance:
1. **Video Processing Backend:**
* Decode incoming video frames.
* Integrate a simple CV model (e.g., pre-trained object detection like YOLOv3-tiny or a Haar cascade face detector).
* Perform inference on frames.
2. **CV Model Service (Conceptual/Integrated):** For now, this might be directly integrated into the Video Processing Backend.
3. **Basic Application Server & API Layer:**
* Develop a minimal REST API endpoint to retrieve CV model results (e.g., list of detected objects).
4. Simple UI/Test Client: Enhance the stream viewer or create a new client to fetch and display CV model results alongside/overlaid on the video.

### Key Functionalities:
* Stream video from camera to backend.
* Process video frames with a CV model.
* Expose CV results via an API.
* Display CV results in the UI/Test Client.

### Quality & Security Focus:
* Input validation for API endpoints.
* Basic authentication for API (e.g., API keys).
* Error handling in the CV processing pipeline.
* Testing CV model accuracy with sample data.

### Best Practices Highlight:
* Define API contracts (e.g., OpenAPI/Swagger).
* Containerize services (Docker).
* Start writing unit and integration tests for the CV pipeline and API.

# Phase 2: Multi-Camera Support, Management & Persistency
**Objective:** Enable the system to handle multiple cameras, allow users to add/configure cameras, and store relevant data.

### Components to Build/Enhance:
1. **Camera Manager / Ingestion Service:**
* Handle connections to multiple cameras concurrently.
* Support dynamic configuration of cameras (e.g., stream URL, credentials).
* Support for at least one other camera type (e.g., USB webcam, if feasible, or another IP camera protocol variant).
2. WebRTC Signaling Server: Scale to manage multiple concurrent signaling sessions.
3. Video Processing Backend: Handle multiple incoming WebRTC streams and associate them with specific CV models.
4. Application Server & API Layer:
* APIs for CRUD operations on cameras (Create, Read, Update, Delete).
* APIs for associating CV models with specific cameras.
* User authentication and basic authorization (e.g., user roles).
5. Database:
* Schema for camera configurations, user accounts, and (optionally) basic CV event logs.
* Integrate DB with the Application Server.
6. User Interface (Basic):
* Pages for listing, adding, and editing cameras.
* Page for viewing live streams from selected cameras.

### Key Functionalities:
* Add and configure multiple cameras through the UI/API.
* View multiple live streams.
* Store camera configurations persistently.
* Basic user login.

### Quality & Security Focus:
* Secure storage of camera credentials (encryption at rest, use of a secrets manager).
* Robust session management and authentication for the UI and API.
* Role-Based Access Control (RBAC) basics.
* Input validation for all camera configuration parameters.
* Scalability testing for signaling and concurrent stream handling.

### Best Practices Highlight:
* Implement CI/CD pipeline.
* Database migration strategy.
* Logging improvements for multi-camera scenarios.

# Phase 3: Advanced CV Features, UI/UX Polish & Alerting
**Objective:** Enhance the CV capabilities, improve the user experience, and add features like model selection and basic alerting.

### Components to Build/Enhance:
1. CV Model Service(s):
* Support for loading and running multiple, different CV models.
* Potentially refactor into a dedicated microservice if complexity grows.
* API for model management (listing available models, perhaps uploading new ones – with security considerations).
2. Video Processing Backend:
* Dynamically route video streams to selected CV models.
* Handle different output formats from various models.
3. Application Server & API Layer:
* APIs for managing CV models and their assignments to cameras.
* APIs for configuring alerts based on CV model outputs (e.g., "alert if person detected in area X").
* Endpoints for querying historical CV event data.
4. User Interface (Enhanced):
* Improved dashboard for camera and CV status.
* Interface for selecting specific CV models per camera.
* Display of model outputs overlaid on video in a more user-friendly way.
* Alert notification system (e.g., UI notifications, email).
5. Database: Schema for CV model metadata, alert configurations, and more detailed event logging.

###  Key Functionalities:
* User can select different CV models for different cameras.
* System can generate alerts based on CV model detections.
* Improved UI for visualization and management.
* Basic querying of historical detection events.

### Quality & Security Focus:
* Security of model management (who can upload/change models).
* Preventing resource exhaustion from too many models or inefficient processing.
* Usability testing for the UI.
* Refine alerting logic to minimize false positives.

### Best Practices Highlight:
* Modular design for CV model integration.
* Asynchronous processing for tasks like sending alert notifications.
* Consider a message queue for decoupling services (e.g., for alerts or model results).

# Phase 4: Production Hardening, Scalability, Optimization & Deployment
**Objective:** Prepare the application for production deployment by focusing on robustness, performance, scalability, comprehensive security, and operational readiness.
**Components to Build/Enhance:** All components are reviewed and hardened.

### Key Functionalities/Activities:
1. Performance Optimization:
* Hardware acceleration for video decoding/encoding (e.g., NVDEC/NVENC, VAAPI).
* Optimize CV model inference times (quantization, model pruning, efficient runtimes).
* Load balancing for all stateful/stateless services.
* Database query optimization.
2. Scalability:
* Horizontal scaling strategies for all services (Camera Ingestion, Signaling, VPB, API, CV Models).
* Use of orchestration (e.g., Kubernetes).
3. Security Hardening:
* Penetration testing.
* Security audit of code and infrastructure.
* Implement advanced security measures (WAF, IDS/IPS, rate limiting, DDoS protection).
* Regular security patching and vulnerability scanning.
* Principle of Least Privilege for all service accounts and user roles.
4. Monitoring & Logging:
* Centralized logging (e.g., ELK stack, Grafana Loki).
* Comprehensive system monitoring and alerting (Prometheus, Grafana) for performance, errors, and resource utilization.
5. Resilience & Fault Tolerance:
* Redundancy for critical components.
* Graceful degradation strategies.
* Automated backups and disaster recovery plan.
6. Deployment Automation:
* Mature CI/CD pipelines for automated deployment to staging and production environments.
* Blue/Green or Canary deployment strategies.
7. Documentation: 
* Finalize all user, operator, and developer documentation.

### Quality & Security Focus:
* Achieving target SLAs (Service Level Agreements) for uptime and performance.
* Passing external security audits.
* Comprehensive disaster recovery testing.

### Best Practices Highlight:
* Full adoption of Infrastructure as Code.
* Chaos engineering principles to test resilience.
* Regular review of security best practices and emerging threats.