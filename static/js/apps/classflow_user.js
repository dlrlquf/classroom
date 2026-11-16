registerUserApp('classflow', () => {
    console.log("Classflow app initialized");
    document.getElementById("ask_question").addEventListener("click", () => {
        socket.emit("classflow_ask_question");
    });
    return () => {};
});