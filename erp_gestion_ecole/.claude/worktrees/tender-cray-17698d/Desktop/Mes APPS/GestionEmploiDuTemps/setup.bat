@echo off
echo ========================================
echo  GestionEDT - Installation automatique
echo ========================================

echo.
echo [1/3] Installation des dependances backend...
cd backend
call npm install
if errorlevel 1 goto error

echo.
echo [2/3] Installation des dependances frontend...
cd ..\frontend
call npm install
if errorlevel 1 goto error

echo.
echo [3/3] Configuration terminee !
echo.
echo ========================================
echo  Etapes suivantes :
echo ========================================
echo.
echo 1. Assurez-vous que PostgreSQL est demarre
echo 2. Copiez backend\.env.example en backend\.env
echo    et configurez DATABASE_URL
echo.
echo 3. Lancez le backend :
echo    cd backend
echo    npm run db:migrate
echo    npm run db:seed
echo    npm run dev
echo.
echo 4. Dans un autre terminal, lancez le frontend :
echo    cd frontend
echo    npm run dev
echo.
echo Frontend : http://localhost:3000
echo Backend  : http://localhost:4000/api/v1
echo Swagger  : http://localhost:4000/docs
echo.
echo Comptes demo :
echo   admin@universite.fr / Admin@1234
echo   prof.martin@universite.fr / Prof@1234
echo   alice.dupont@etu.fr / Student@1234
echo ========================================
goto end

:error
echo ERREUR lors de l'installation !
exit /b 1

:end
pause
